#import dependencies
import os # To get the environment variables
import logging
from fastapi import FastAPI, HTTPException, status
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import json
from decimal import Decimal

#get the name of queue, dynamoDB table name, aws region name
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DynamoDB_Table = os.environ.get("DYNAMODB_TABLE")
SQSQueue_URl = os.environ.get("QUEUE_URL")

#Creating service resource objects from boto3 for AWS services[Queue, dynamoDB Table]
sqsQueueResource = boto3.client("sqs", region_name = AWS_REGION)
dynamoDBResource = boto3.resource("dynamodb", region_name = AWS_REGION)
tableResource = dynamoDBResource.Table(DynamoDB_Table)

#Set logger configuration to show on console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FraudDetectionLogger")

#Initializing app
app = FastAPI(title="Banking Fraud Detection API")

#create a dataModel class for transaction
class Transaction(BaseModel) :
    accountId:str = Field(..., min_length=1, examples=["ACC-9981A"])
    amount:float = Field(...,  gt=0.0, examples=[250.75])
    transactionType: str = Field(..., examples=["withdrawal", "deposit", "transfer"])
    location: str = Field(..., min_length=1, examples=["Oakville, ON"])
    failedLoginAttempts: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
#API post to post transactions [routing]
@app.post("/api/transactions", status_code=status.HTTP_201_CREATED)
async def function(transaction : Transaction) :

    is_suspicious = False
    fraudReasons = []
    
    # FIX: Partition Key changed to "incident_id" to match your active AWS infrastructure schema
    transactionLog = {
    "incident_id": f"TRN#{transaction.accountId}#{transaction.timestamp.isoformat()}",
    "recordType" : "TRANSACTION LOG",
    "accountId" : transaction.accountId,
    "transactionType" : transaction.transactionType,
    "location" : transaction.location,
    "failedLoginAttempts" : transaction.failedLoginAttempts,
    "status" : "approved",
    "amount": Decimal(str(transaction.amount)),
    "timestamp" : transaction.timestamp.isoformat()
    }
    
    #rule 1: check login failedLoginAttempts
    if(transaction.failedLoginAttempts >= 3):
        is_suspicious = True
        fraudReasons.append("Too many failed login attempts! Activity Suspicious!")

    # rule 2: unusually large withdrawal amount [>10000]
    if(transaction.transactionType == "withdrawal" and transaction.amount >= 10000) :
        is_suspicious = True
        fraudReasons.append("Unusually large amount requested! Activity Suspicious!")

    # rule 3: location check 
    try:
        incidentRecords = tableResource.scan(
            FilterExpression=Key("incident_id").begins_with(f"TRN#{transaction.accountId}")
        )
        
        items = incidentRecords.get("Items", [])
        if len(items) > 0:
            items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            lastRecord = items[0]
            
            last_time = datetime.fromisoformat(lastRecord.get("timestamp")).replace(tzinfo=timezone.utc)
            current_time = transaction.timestamp.replace(tzinfo=timezone.utc)
            time_delta = (current_time - last_time).total_seconds()
            
            current_city = transaction.location.split(",")[0].strip().lower()
            last_city = lastRecord.get("location", "").split(",")[0].strip().lower() if lastRecord.get("location") else ""
            
            # If the location changed and it is within 15 minutes (900 seconds)
            if (time_delta < 900 and current_city != last_city): 
                is_suspicious = True
                fraudReasons.append("Geolocation changed within a short timespan! Activity Suspicious!")
        else:
            logger.info(f"No history found. Initializing profile tracking context for: {transaction.accountId}")
            
    except Exception as e:
        logger.error(f"Failed to scan DynamoDB history context. Exception: {str(e)}")
    
    try:
        if is_suspicious :
            transactionLog["status"] = "flagged"
            
            sqsQueueItem = transactionLog.copy()
            sqsQueueItem["amount"] = str(transactionLog["amount"])
            
            sqsQueueResource.send_message(
                QueueUrl=SQSQueue_URl,
                MessageBody=json.dumps(sqsQueueItem)
            )
    except Exception as e:
        logger.error(f"Failed to push transaction to SQS Queue Exception : {str(e)}")
    
    #push to database
    try:
        tableResource.put_item(Item=transactionLog)
    except Exception as e:
        logger.error(f"Failed to log transaction to dynamoDB Exception : {str(e)}")
        raise HTTPException(status_code=500, detail="Database write synchronization failure.")

    return {
        "TransactionID" : transactionLog["incident_id"],   
        "status" : transactionLog["status"],
        "RulesViolated" : len(fraudReasons)
    }