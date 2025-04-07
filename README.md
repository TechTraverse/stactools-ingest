# Stactools-Ingest

This repository provides infrastructure and code for a serverless STAC ingestion system built on AWS. It allows for asynchronous generation and loading of STAC items into a `pgstac` database through a two-phase workflow managed by SNS topics and SQS queues.

## Architecture Overview

The stactools-ingest pipeline is a cloud-native, event-driven architecture designed to efficiently generate and load STAC (SpatioTemporal Asset Catalog) items into a PostgreSQL database with the pgstac extension. The system consists of two primary processing stages connected through SNS topics and SQS queues to ensure reliable message delivery and processing.

## Core Components

### 1. Message Queuing Infrastructure

**Item Generation Stage:**

- **SNS Topic (`ItemGenTopic`)**: Entry point for triggering item generation workflows
- **SQS Queue (`ItemGenQueue`)**: Buffers generation requests with 120-second visibility timeout
- **Dead Letter Queue (`ItemGenDeadLetterQueue`)**: Captures failed messages after 5 processing attempts

**Item Loading Stage:**

- **SNS Topic (`ItemLoadTopic`)**: Receives generated STAC items ready for database insertion
- **SQS Queue (`ItemLoadQueue`)**: Batches items before database loading with 60-second visibility timeout
- **Dead Letter Queue (`ItemLoadDeadLetterQueue`)**: Captures failed loading attempts after 5 retries

### 2. Processing Functions

**Item Generation Function:**

- Containerized Lambda function built with Docker
- Processes incoming messages that describe source data
- Generates standardized STAC items and publishes them to the Item Load Topic
- Configured with 1024MB memory and 120-second timeout

**Item Loading Function:**

- Python Lambda function
- Receives batches of up to 1000 STAC items
- Inserts items into the pgstac database
- Configured with 1024MB memory and 45-second timeout
- Securely accesses database credentials via AWS Secrets Manager

## Data Flow

1. External systems publish messages to the `ItemGenTopic` with metadata about assets to be processed
2. The `ItemGenQueue` buffers these messages and triggers the Item Generation Lambda
3. The Item Generation Lambda:
   - Processes each message
   - Transforms source data into STAC items
   - Publishes the STAC items to the `ItemLoadTopic`
4. The `ItemLoadQueue` collects STAC items and batches them (up to 1000 items or 1 minute)
5. The Item Loading Lambda:
   - Receives batches of STAC items
   - Connects to the pgstac database
   - Inserts the items into the database

## Operational Characteristics

- **Scalability**: Lambda functions scale automatically based on incoming message volume
- **Reliability**: Dead letter queues capture failed processing attempts for debugging and retry
- **Efficiency**: Batching in the Item Loading stage optimizes database operations
- **Observability**: CloudWatch logs retain function execution details for one week

## Deployment

This repository contains an AWS CDK app file ([`app.py`](./infrastructure/app.py)) with all of the components required to stand up a `pgstac` database and the ingestion pipelines.
To deploy this stack, create a config.yml file and populate it with settings to be passed to [`config.py`](./infrastructure/config.py) then run:

```bash
uv sync --all-groups
uv run cdk deploy --all
```

## How to Use

This section walks through an example workflow for interacting with the ingestion infrastructure.
It uses the stactools package [`stactools-glad-glclu2020`](https://github.com/stactools-packages/glad-glclu2020) which can be used to generate STAC metadata for the GLAD Global Landcover and Landuse 2020 dataset.
For production applications all of this would be less manual but this example shows the basic steps.

### Prerequisites

- AWS CLI configured with appropriate permissions
- Access to the deployed AWS resources
- Collections loaded into pgstac database

### Load Collections

Create a collection json so we can upload items with this collection id!

```bash
uvx --with=requests,stactools-glad-glclu2020 --from=stactools stac gladglclu2020 create-collection \
  --sample-asset-href https://storage.googleapis.com/earthenginepartners-hansen/GLCLU2000-2020/v2/2000/50N_090W.tif \
  --type annual \
  /tmp/collection.json
```

Upload it to pgstac:

```bash
PGSTAC_STACK=stactools-ingest-test-pgstac
SECRET_ARN=$(aws cloudformation describe-stacks --stack-name $PGSTAC_STACK --query "Stacks[0].Outputs[?OutputKey=='PgstacSecret'].OutputValue" --output text)
SECRET_VALUE=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_ARN" \
  --query "SecretString" \
  --output text) 

export PGHOST=$(echo "$SECRET_VALUE" | jq -r '.host')
export PGPORT=$(echo "$SECRET_VALUE" | jq -r '.port')
export PGDATABASE=$(echo "$SECRET_VALUE" | jq -r '.dbname')
export PGUSER=$(echo "$SECRET_VALUE" | jq -r '.username')
export PGPASSWORD=$(echo "$SECRET_VALUE" | jq -r '.password')

uvx --from="pypgstac[psycopg]==0.9.5" pypgstac load collections --method=upsert /tmp/collection.json
```

### Initiating the item generation and ingestion workflow

To generate and load STAC items, publish a message to the Item Generation SNS topic.
The ItemGen function will use `uvx` to install the required stactools package then execute the `create-item` CLI command with the provided arguments.
The message schema must match the `ItemRequest` model defined in [`item_gen/item.py`](./packages/item-gen/src/item_gen/item.py).

```bash
STACK_NAME=stactools-ingest-test
ITEM_GEN_TOPIC=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='ItemGenSNSTopicArn'].OutputValue" --output text)

aws sns publish --topic-arn $ITEM_GEN_TOPIC --message '{
  "package_name": "stactools-glad-glclu2020",
  "group_name": "gladglclu2020",
  "create_item_args": [
    "https://storage.googleapis.com/earthenginepartners-hansen/GLCLU2000-2020/v2/2000/50N_090W.tif"
  ]
}'
```

If the item is generated successfully, it will be forwarded onto the `ItemLoad` part of the pipeline.

To monitor the logs for the `ItemGen` function:

```bash
ITEM_GEN_FUNCTION=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='ItemGenFunctionName'].OutputValue" --output text)

aws logs tail /aws/lambda/$ITEM_GEN_FUNCTION --follow
```

To monitor the logs for the `ItemLoad` function:

```bash
ITEM_LOAD_FUNCTION=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='ItemLoadFunctionName'].OutputValue" --output text)

aws logs tail /aws/lambda/$ITEM_LOAD_FUNCTION --follow
```

### Example for ingesting many items

You may want to send `ItemGen` tasks in batches. Here is a workflow for posting messages to the `ItemGen` SNS topic in a loop. The `ItemGen` function will post STAC item jsons to the `ItemLoad` SNS topic, which will get consumed  by the `ItemLoad` SQS queue and processed by the `ItemLoad` Lambda function (in batches).

```bash
INVENTORY_URL=https://storage.googleapis.com/earthenginepartners-hansen/GLCLU2000-2020/v2/2000.txt
curl -s "$INVENTORY_URL" > urls.txt

count=0
total=$(wc -l < urls.txt)

while IFS= read -r url; do
    count=$((count + 1))
    echo "Processing $count of $total: $url"
    
    # Run the AWS SNS publish command with the current URL
    aws sns publish --topic-arn "$ITEM_GEN_TOPIC" --message "{
        \"package_name\": \"stactools-glad-glclu2020\",
        \"group_name\": \"gladglclu2020\",
        \"create_item_args\": [
            \"$url\"
        ]
    }"
    
done < urls.txt

echo "Completed processing $count URLs."
```

```bash
# Get DLQ URLs
ITEM_GEN_DLQ=$(aws cloudformation describe-stacks --stack-name <your-stack-name> --query "Stacks[0].Outputs[?OutputKey=='ItemGenDLQUrl'].OutputValue" --output text)
ITEM_LOAD_DLQ=$(aws cloudformation describe-stacks --stack-name <your-stack-name> --query "Stacks[0].Outputs[?OutputKey=='ItemLoadDLQUrl'].OutputValue" --output text)

# Check for failed messages
aws sqs get-queue-attributes --queue-url $ITEM_GEN_DLQ --attribute-names ApproximateNumberOfMessages
aws sqs get-queue-attributes --queue-url $ITEM_LOAD_DLQ --attribute-names ApproximateNumberOfMessages
```

### Advanced: Direct Access to Item Load Topic

This pipeline is designed to be modular such that any service that can produce valid STAC item JSON documents could post messages directly to the ItemLoad SNS topic in order to add those items to the queue.

```bash
ITEM_LOAD_TOPIC=$(aws cloudformation describe-stacks --stack-name <your-stack-name> --query "Stacks[0].Outputs[?OutputKey=='ItemLoadTopicArn'].OutputValue" --output text)

# Publish a pre-generated STAC item
aws sns publish --topic-arn $ITEM_LOAD_TOPIC --message '{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "example-item",
  "properties": {
    "datetime": "2021-01-01T00:00:00Z"
  },
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]
  },
  "links": [],
  "assets": {},
  "collection": "example-collection"
}'
```

## Error Handling

The system includes several error handling mechanisms:

1. **Dead-Letter Queues**: Failed messages are sent to DLQs for inspection and replay
2. **Batch Item Failures**: Lambda functions report individual failures within batches
3. **Comprehensive Logging**: Detailed logs for troubleshooting
