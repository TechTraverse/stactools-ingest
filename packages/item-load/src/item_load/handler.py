import base64
import json
import logging
import os
from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    DefaultDict,
    Dict,
    List,
    Optional,
    TypedDict,
)

import boto3.session
from pypgstac.db import PgstacDB
from pypgstac.load import Loader, Methods
from stac_pydantic.item import Item

if TYPE_CHECKING:
    from aws_lambda_typing.context import Context
else:
    Context = Annotated[object, "Context object"]

logger = logging.getLogger()
if logger.hasHandlers():
    logger.handlers.clear()

log_handler = logging.StreamHandler()  # <--- Renamed handler variable

log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
log_level = logging._nameToLevel.get(log_level_name, logging.INFO)
logger.setLevel(log_level)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)


class BatchItemFailure(TypedDict):
    itemIdentifier: str


class PartialBatchFailureResponse(TypedDict):
    batchItemFailures: List[BatchItemFailure]


def get_secret_dict(secret_name: str) -> Dict:
    """Retrieve secrets from AWS Secrets Manager

    Args:
        secret_name (str): name of aws secrets manager secret containing database connection secrets
        profile_name (str, optional): optional name of aws profile for use in debugger only

    Returns:
        secrets (dict): decrypted secrets in dict
    """

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager")

    get_secret_value_response = client.get_secret_value(SecretId=secret_name)

    if "SecretString" in get_secret_value_response:
        return json.loads(get_secret_value_response["SecretString"])
    else:
        return json.loads(base64.b64decode(get_secret_value_response["SecretBinary"]))


def get_rds_token(host: str, user: str, port: str) -> str:
    """Generate an RDS IAM authentication token

    Returns:
        token (str): IAM authentication token for RDS
    """
    session = boto3.session.Session()
    rds_client = session.client("rds")

    try:
        token = rds_client.generate_db_auth_token(
            DBHostname=host,
            Port=port,
            DBUsername=user
        )
        logger.info("Successfully generated IAM token for RDS.")
        return token
    except Exception as e:
        logger.error(f"Failed to generate IAM token: {str(e)}")
        raise


def get_pgstac_dsn() -> str:
    secret_arn = os.getenv("PGSTAC_SECRET_ARN")
    if secret_arn:
        secret_dict = get_secret_dict(secret_name=secret_arn)
        return f"postgres://{secret_dict['username']}:{secret_dict['password']}@{secret_dict['host']}:{secret_dict['port']}/{secret_dict['dbname']}"

    # Fallback to IAM authentication if PGSTAC_SECRET_ARN is not set
    postgres_host = os.getenv("POSTGRES_HOST")
    postgres_dbname = os.getenv("POSTGRES_DBNAME")
    postgres_user = os.getenv("POSTGRES_USER")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")

    if not (postgres_host and postgres_dbname and postgres_user):
        logger.error("Environment variables POSTGRES_HOST, POSTGRES_DBNAME, and POSTGRES_USER must be set for IAM authentication.")
        raise EnvironmentError("Missing required environment variables for IAM authentication.")

    token = get_rds_token(
        host=postgres_host,
        user=postgres_user,
        port=postgres_port
    )

    return f"postgres://{postgres_user}:{token}@{postgres_host}:{postgres_port}/{postgres_dbname}"


def handler(
    event: Dict[str, Any], context: Context
) -> Optional[PartialBatchFailureResponse]:
    records = event.get("Records", [])
    aws_request_id = getattr(context, "aws_request_id", "N/A")
    remaining_time = getattr(context, "get_remaining_time_in_millis", lambda: "N/A")()

    logger.info(f"Received batch with {len(records)} records.")
    logger.debug(
        f"Lambda Context: RequestId={aws_request_id}, RemainingTime={remaining_time}ms"
    )
    pgstac_dsn = get_pgstac_dsn()

    batch_item_failures: List[BatchItemFailure] = []

    items_by_collection: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    message_ids_by_collection: DefaultDict[str, List[str]] = defaultdict(list)
    for record in records:
        message_id = record.get("messageId")
        if not message_id:
            logger.warning("Record missing messageId, cannot report failure for it.")
            continue

        try:
            sqs_body_str = record["body"]
            logger.debug(f"[{message_id}] SQS message body: {sqs_body_str}")
            sns_notification = json.loads(sqs_body_str)

            message_str = sns_notification["Message"]
            logger.debug(f"[{message_id}] SNS Message content: {message_str}")

            message_data = json.loads(message_str)
            item = Item(**message_data)

            # validate item
            if not item.collection:
                raise Exception

            items_by_collection[item.collection].append(item.model_dump(mode="json"))
            message_ids_by_collection[item.collection].append(message_id)
            logger.info(f"[{message_id}] Successfully processed.")

        except Exception:
            logger.error(f"[{message_id}] Marked as failed.")
            batch_item_failures.append({"itemIdentifier": message_id})

    for collection_id, items in items_by_collection.items():
        try:
            with PgstacDB(dsn=pgstac_dsn) as db:
                loader = Loader(db=db)
                logger.info(f"[{collection_id}] loading items into database.")
                loader.load_items(
                    file=items,  # type: ignore
                    # use insert_ignore to avoid overwritting existing items or upsert to replace
                    insert_mode=Methods.upsert,
                )
                logger.info(f"[{collection_id}] successfully loaded items.")
        except Exception as e:
            logger.error(f"[{collection_id}] failed to load items: {str(e)}")

            batch_item_failures.extend(
                [
                    {"itemIdentifier": message_id}
                    for message_id in message_ids_by_collection[collection_id]
                ]
            )

    if batch_item_failures:
        logger.warning(
            f"Finished processing batch. {len(batch_item_failures)} failure(s) reported."
        )
        logger.info(
            f"Returning failed item identifiers: {[f['itemIdentifier'] for f in batch_item_failures]}"
        )
        return {"batchItemFailures": batch_item_failures}
    else:
        logger.info("Finished processing batch. All records successful.")
        return None
