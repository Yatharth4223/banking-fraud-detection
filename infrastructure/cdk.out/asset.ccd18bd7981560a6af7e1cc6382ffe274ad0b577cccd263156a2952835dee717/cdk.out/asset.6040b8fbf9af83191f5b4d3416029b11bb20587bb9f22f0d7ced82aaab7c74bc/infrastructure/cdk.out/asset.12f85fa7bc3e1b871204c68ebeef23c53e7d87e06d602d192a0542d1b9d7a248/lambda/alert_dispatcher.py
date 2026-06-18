import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

# Set up system logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alert-dispatcher")

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "security@yourbank.com")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Initialize the AWS SDK resources
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)
ses_client = boto3.client("ses", region_name=AWS_REGION)

def lambda_handler(event, context):

    logger.info(f"Processing a batch of {len(event['Records'])} SQS event messages.")
    
    #Listening to SQS Queue
    for record in event["Records"]:
        try:
            transaction_data = json.loads(record["body"])
            account_id = transaction_data.get("account_id")
            amount_raw = transaction_data.get("amount")
            amount = float(amount_raw) if amount_raw else 0.0
            location = transaction_data.get("location")
            fraud_metrics = transaction_data.get("fraud_metrics", ["General profile anomaly"])
            
            logger.warning(f"[ALERT] Processing critical fraud event for Account: {account_id}")

            #Flagging record type as a fraud incident for DynamoDB
            transaction_data["record_type"] = "FRAUD_INCIDENT"
            
            table.put_item(Item=transaction_data)
            logger.info(f"Security incident permanently logged to database for account: {account_id}")

            #Sending email alert to the customer
            recipient_email = f"customer_{account_id}@example.com" 
            send_security_alert_email(recipient_email, account_id, amount, location, fraud_metrics)
            
        except Exception as e:
            logger.error(f"Critical structural failure processing queue item: {str(e)}")
            raise e

    return {"status": "SUCCESS", "processed_records": len(event["Records"])}


def send_security_alert_email(recipient, account_id, amount, location, reasons):

    subject = "URGENT: Your Bank Account Transaction Has Been Paused"
    
    reasons_list_text = "\n".join([f"- {reason}" for reason in reasons])
    body_text = f"""
    Dear Customer,
    
    Our automated fraud prevention network has detected suspicious activity on your account and temporarily paused a pending transaction.
    
    Security Incident Summary:
    --------------------------------------
    Account ID: {account_id}
    Transaction Amount: ${amount:.2f}
    Location Tracked: {location}
    
    Flagged Detection System Triggers:
    {reasons_list_text}
    
    If this was you: Please open your banking application dashboard to verify your identity.
    If this was NOT you: Call our fraud hotline immediately to lock your credentials.
    
    Sincerely,
    Global Fraud Prevention Squad
    """
    
    try:
        ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body_text}}
            }
        )
        logger.info(f"Outbound alert email dispatched to {recipient} successfully.")
        
    except ClientError as e:
        logger.error(f"Failed to dispatch email alert through Amazon SES: {e.response['Error']['Message']}")