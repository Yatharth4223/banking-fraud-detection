#importing core libraries
import os

import aws_cdk as cdk

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_events,
    aws_iam as iam,
    RemovalPolicy,
    Duration
)

from constructs import Construct

class PracticeCdkStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Sets up public subnets for the ALB and private subnets for the containers
        vpc = ec2.Vpc(
            self, "SecureBankingVPC",
            max_azs=2,  
            nat_gateways=1 
        )

        #Creating cluster for ECS Fargate
        cluster = ecs.Cluster(self, "BankingEcsCluster", vpc=vpc)

        #Setting up DynamoDB table
        table = dynamodb.Table(
            self, "FraudLogsTable",
            table_name="BankingFraudLogs",
            partition_key=dynamodb.Attribute(name="incident_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  
            removal_policy=RemovalPolicy.DESTROY 
        )

        #Setting up SQS queue
        queue = sqs.Queue(
            self, "FraudEventQueue",
            queue_name="banking-fraud-queue",
            visibility_timeout=Duration.seconds(30) 
        )

        #setting up IAM role and permissions
        ecs_task_role = iam.Role(
            self, "EcsTaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        
        table.grant_read_write_data(ecs_task_role)  
        queue.grant_send_messages(ecs_task_role)   

        current_dir = os.path.dirname(os.path.abspath(__file__))
        lambda_path = os.path.join(current_dir, "../lambda")
        project_root_path = os.path.join(current_dir, "..")

        #Setting up Lambda function for customer notifications
        notifier_lambda = _lambda.Function(
            self, "CustomerNotifierLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset(lambda_path),  
            handler="alert_dispatcher.lambda_handler",  
            environment={
                "DYNAMODB_TABLE": table.table_name,
                "SENDER_EMAIL": "security-alerts@yourbank.com"  
            }
        )

        table.grant_read_write_data(notifier_lambda)  
        queue.grant_consume_messages(notifier_lambda) 
        notifier_lambda.add_event_source(lambda_events.SqsEventSource(queue))  

        notifier_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=["ses:SendEmail", "ses:SendRawEmail"],
            resources=["*"]  
        ))



        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "FraudIngestionApiService",
            cluster=cluster,
            public_load_balancer=True,  
            cpu=256,                    
            memory_limit_mib=512,       
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(directory=project_root_path),  
                container_port=8000,                                   
                task_role=ecs_task_role,                               
                environment={
                    "QUEUE_URL": queue.queue_url,
                    "DYNAMODB_TABLE": table.table_name,
                    "AWS_REGION": self.region
                }
            )
        )

        fargate_service.target_group.configure_health_check(
            path="/docs",  # Uses your Swagger docs route to verify container health status
            healthy_http_codes="200"
        )

app = cdk.App()
PracticeCdkStack(app, "PracticeCdkStack")
app.synth()


