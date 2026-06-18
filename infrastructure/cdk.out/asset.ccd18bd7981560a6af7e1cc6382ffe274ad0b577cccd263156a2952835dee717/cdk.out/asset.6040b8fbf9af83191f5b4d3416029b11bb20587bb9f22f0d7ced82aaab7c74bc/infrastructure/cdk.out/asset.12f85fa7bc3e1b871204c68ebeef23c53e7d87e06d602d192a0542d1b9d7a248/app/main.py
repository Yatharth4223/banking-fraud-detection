import os
import json
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal

#Setting logger configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fraud-detector")

app = FastAPI(title="Banking Fraud Detection Core API")

SQS_QUEUE_URL = os.environ.get("QUEUE_URL")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Initialize AWS Boto3
sqs_resource = boto3.client("sqs", region_name=AWS_REGION)
dynamodb_resource = boto3.resource("dynamodb", region_name=AWS_REGION)
table_resource = dynamodb_resource.Table(DYNAMODB_TABLE)

class TransactionPayload(BaseModel):
    account_id: str = Field(..., min_length=1, examples=["ACC-9981A"])
    amount: float = Field(..., gt=0.0, examples=[250.75])
    transaction_type: str = Field(..., examples=["withdrawal", "deposit", "transfer"])
    location: str = Field(..., min_length=1, examples=["Oakville, ON"])
    failed_login_attempts: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


#Fraud Detection Component
@app.post("/api/v1/transactions", status_code=status.HTTP_201_CREATED)
async def process_transaction(payload: TransactionPayload):
    current_time_str = payload.timestamp.isoformat()
    is_suspicious = False
    fraud_reasons = []

    # Standard Database record
    transaction_item = {
        "incident_id": f"TXN#{payload.account_id}#{current_time_str}",
        "record_type": "TRANSACTION_LOG",
        "account_id": payload.account_id,
        "amount": Decimal(str(payload.amount)),
        "transaction_type": payload.transaction_type,
        "location": payload.location,
        "failed_login_attempts": payload.failed_login_attempts,
        "timestamp": current_time_str,
        "status": "approved" # Default state assumption
    }

    # Fraud Detection Rule 1: Too many failed login attempts
    if payload.failed_login_attempts >= 3:
        is_suspicious = True
        fraud_reasons.append(f"High risk authentication: {payload.failed_login_attempts} failed login attempts.")
    
    # Fraud Detection Rule 2: Unusually large withdrawal amounts
    if payload.transaction_type == "withdrawal" and payload.amount > 10000.00:
        is_suspicious = True
        fraud_reasons.append(f"Unusually large withdrawal volume: ${payload.amount}")

    # Fraud Detection Rule 3: Transaction from a different geographic regions within a short time.
    try:
        historical_records = table_resource.query(
            KeyConditionExpression=Key("incident_id").begins_with(f"TXN#{payload.account_id}"),
            ScanIndexForward=False,
            Limit=1
        )
        
        if historical_records.get("Items"):
            last_transaction = historical_records["Items"][0]
            last_location = last_transaction.get("location")
            last_time = datetime.fromisoformat(last_transaction.get("timestamp"))
            
            if last_location != payload.location:
                time_delta = (payload.timestamp - last_time).total_seconds()
                if time_delta < 900:
                    is_suspicious = True
                    fraud_reasons.append(
                        f"Impossible travel anomaly: Moved from {last_location} to {payload.location} "
                        f"in {int(time_delta)} seconds."
                    )
    except Exception as e:
        logger.error(f"Failed to query historical ledger records from DynamoDB: {str(e)}")

    if is_suspicious:
        logger.critical(f"[FRAUD DETECTED] Account {payload.account_id} flagged! Reasons: {fraud_reasons}")
        
        # Marking state record layout as flagged
        transaction_item["status"] = "flagged"
        transaction_item["fraud_metrics"] = fraud_reasons
        
        #Pushing Flagged transactions to SQS Queue.
        try:

            sqs_payload = transaction_item.copy()

            sqs_payload["amount"] = str(transaction_item["amount"]) 

            sqs_resource.send_message(
                QueueUrl=SQS_QUEUE_URL,
                MessageBody=json.dumps(sqs_payload)
            )
        except Exception as e:
            logger.error(f"Critical SQS pipeline delivery failure: {str(e)}")
            raise HTTPException(status_code=500, detail="Core processing telemetry pipeline error.")
    else:
        logger.info(f"[TRANSACTION APPROVED] Account {payload.account_id} cleared standard fraud checks.")

    # Logging all transactions to DynamoDB
    try:
        table_resource.put_item(Item=transaction_item)
    except Exception as e:
        logger.error(f"Failed to commit audit record log to DynamoDB: {str(e)}")
        raise HTTPException(status_code=500, detail="Database write synchronization failure.")

    return {
        "transaction_id": transaction_item["incident_id"],
        "status": transaction_item["status"],
        "evaluations_triggered": len(fraud_reasons)
    }
