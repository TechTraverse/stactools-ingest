import os

from aws_cdk import (
    App,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_ec2,
    aws_lambda,
    aws_lambda_event_sources,
    aws_logs,
    aws_rds,
    aws_sns,
    aws_sns_subscriptions,
    aws_sqs,
)
from aws_cdk.aws_ecr_assets import Platform
from config import AppConfig
from constructs import Construct
from eoapi_cdk import (
    PgStacApiLambda,
    PgStacDatabase,
)

PGSTAC_VERSION = "0.9.5"


class VpcStack(Stack):
    def __init__(
        self, scope: Construct, app_config: AppConfig, id: str, **kwargs
    ) -> None:
        super().__init__(scope, id=id, tags=app_config.tags, **kwargs)

        self.vpc = aws_ec2.Vpc(
            self,
            "vpc",
            subnet_configuration=[
                aws_ec2.SubnetConfiguration(
                    name="ingress", subnet_type=aws_ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
                aws_ec2.SubnetConfiguration(
                    name="application",
                    subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                aws_ec2.SubnetConfiguration(
                    name="rds",
                    subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
            nat_gateways=app_config.nat_gateway_count,
        )

        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=aws_ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
        )

        self.vpc.add_interface_endpoint(
            "CloudWatchEndpoint",
            service=aws_ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
        )

        self.vpc.add_gateway_endpoint(
            "S3", service=aws_ec2.GatewayVpcEndpointAwsService.S3
        )

        self.export_value(
            self.vpc.select_subnets(subnet_type=aws_ec2.SubnetType.PUBLIC)
            .subnets[0]
            .subnet_id
        )
        self.export_value(
            self.vpc.select_subnets(subnet_type=aws_ec2.SubnetType.PUBLIC)
            .subnets[1]
            .subnet_id
        )


class PgstacStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        app_config: AppConfig,
        vpc: aws_ec2.Vpc,
        **kwargs,
    ) -> None:
        super().__init__(
            scope,
            id=id,
            tags=app_config.tags,
            **kwargs,
        )

        self.db = PgStacDatabase(
            self,
            "pgstac-db",
            vpc=vpc,
            engine=aws_rds.DatabaseInstanceEngine.postgres(
                version=aws_rds.PostgresEngineVersion.VER_16
            ),
            vpc_subnets=aws_ec2.SubnetSelection(subnet_type=aws_ec2.SubnetType.PUBLIC),
            allocated_storage=app_config.db_allocated_storage,
            instance_type=aws_ec2.InstanceType(app_config.db_instance_type),
            removal_policy=RemovalPolicy.DESTROY,
            custom_resource_properties={
                "context": True,
                "mosaic_index": True,
            },
            add_pgbouncer=True,
            pgstac_version=PGSTAC_VERSION,
        )

        # allow connections from any ipv4 to pgbouncer instance security group
        assert self.db.security_group
        self.db.security_group.add_ingress_rule(
            aws_ec2.Peer.any_ipv4(), aws_ec2.Port.tcp(5432)
        )

        self.stac_api = PgStacApiLambda(
            self,
            "stac-api",
            db=self.db.connection_target,
            db_secret=self.db.pgstac_secret,
        )

        CfnOutput(
            self,
            "PgstacSecret",
            value=self.db.pgstac_secret.secret_arn,
            description="ARN of the pgstac secret",
        )


class StactoolsIngestStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        app_config: AppConfig,
        pgstac_db: PgStacDatabase,
        context_dir: str = "./",
        lambda_runtime: aws_lambda.Runtime = aws_lambda.Runtime.PYTHON_3_11,
        **kwargs,
    ) -> None:
        super().__init__(
            scope,
            id=id,
            tags=app_config.tags,
            **kwargs,
        )

        item_gen_lambda_timeout_seconds = 120

        # --- item-gen SNS and SQS ---
        item_gen_dlq = aws_sqs.Queue(
            self,
            "ItemGenDeadLetterQueue",
            retention_period=Duration.days(14),
        )

        item_gen_queue = aws_sqs.Queue(
            self,
            "ItemGenQueue",
            visibility_timeout=Duration.seconds(item_gen_lambda_timeout_seconds + 10),
            encryption=aws_sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=aws_sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=item_gen_dlq,
            ),
        )

        item_gen_topic = aws_sns.Topic(
            self,
            "ItemGenTopic",
            display_name=f"{id}-ItemGenTopic",
        )

        item_gen_topic.add_subscription(
            aws_sns_subscriptions.SqsSubscription(item_gen_queue)
        )

        # --- item-load SNS and SQS ---
        item_load_dlq = aws_sqs.Queue(
            self,
            "ItemLoadDeadLetterQueue",
            retention_period=Duration.days(14),
        )

        item_load_queue = aws_sqs.Queue(
            self,
            "ItemLoadQueue",
            visibility_timeout=Duration.seconds(60),
            encryption=aws_sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=aws_sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=item_load_dlq,
            ),
        )

        item_load_topic = aws_sns.Topic(
            self,
            "ItemLoadTopic",
            display_name=f"{id}-ItemLoadTopic",
        )

        item_load_topic.add_subscription(
            aws_sns_subscriptions.SqsSubscription(item_load_queue)
        )

        # Lambdas
        item_gen_function = aws_lambda.DockerImageFunction(
            self,
            "ItemGenFunction",
            code=aws_lambda.DockerImageCode.from_image_asset(
                directory=os.path.abspath(context_dir),
                file="infrastructure/item_gen/Dockerfile",
                platform=Platform.LINUX_AMD64,
                build_args={
                    "PYTHON_VERSION": lambda_runtime.to_string().replace("python", ""),
                },
            ),
            memory_size=1024,
            timeout=Duration.seconds(item_gen_lambda_timeout_seconds),
            log_retention=aws_logs.RetentionDays.ONE_WEEK,
            environment={
                "ITEM_LOAD_TOPIC_ARN": item_load_topic.topic_arn,
                "LOG_LEVEL": "INFO",  # Example: make log level configurable
            },
        )

        item_load_topic.grant_publish(item_gen_function)

        item_gen_function.add_event_source(
            aws_lambda_event_sources.SqsEventSource(
                item_gen_queue,
                batch_size=10,
                report_batch_item_failures=True,
                max_concurrency=100,
            )
        )

        item_load_function = aws_lambda.Function(
            self,
            "ItemLoadFunction",
            runtime=lambda_runtime,
            handler="item_load.handler.handler",
            code=aws_lambda.Code.from_docker_build(
                path=os.path.abspath(context_dir),
                file="infrastructure/item_load/Dockerfile",
                platform="linux/amd64",
                build_args={
                    "PYTHON_VERSION": lambda_runtime.to_string().replace("python", ""),
                },
            ),
            memory_size=1024,
            timeout=Duration.seconds(45),
            log_retention=aws_logs.RetentionDays.ONE_WEEK,
            environment={
                "PGSTAC_SECRET_ARN": pgstac_db.pgstac_secret.secret_arn,
            },
        )
        pgstac_db.pgstac_secret.grant_read(item_load_function)

        item_load_function.add_event_source(
            aws_lambda_event_sources.SqsEventSource(
                item_load_queue,
                batch_size=1000,
                max_batching_window=Duration.minutes(1),
                report_batch_item_failures=True,
            )
        )

        item_load_topic.grant_publish(item_gen_function)

        CfnOutput(
            self,
            "ItemGenSNSTopicArn",
            value=item_gen_topic.topic_arn,
            description="ARN of the Initial SNS Topic to publish messages to",
        )
        CfnOutput(self, "ItemGenQueueUrl", value=item_gen_queue.queue_url)
        CfnOutput(self, "ItemGenDLQUrl", value=item_gen_dlq.queue_url)
        CfnOutput(self, "ItemGenFunctionName", value=item_gen_function.function_name)

        CfnOutput(
            self,
            "ItemLoadTopicArn",
            value=item_load_topic.topic_arn,
            description="ARN of the SNS Topic for loading STAC items into the database",
        )
        CfnOutput(self, "ItemLoadQueueUrl", value=item_load_queue.queue_url)
        CfnOutput(self, "ItemLoadDLQUrl", value=item_load_dlq.queue_url)
        CfnOutput(self, "ItemLoadFunctionName", value=item_load_function.function_name)


app = App()

app_config = AppConfig()

vpc_stack = VpcStack(
    app,
    id=f"{app_config.project_id}-{app_config.stage}-vpc",
    app_config=app_config,
)

pgstac_stack = PgstacStack(
    app,
    id=f"{app_config.project_id}-{app_config.stage}-pgstac",
    app_config=app_config,
    vpc=vpc_stack.vpc,
)

stactools_ingest_stack = StactoolsIngestStack(
    app,
    f"{app_config.project_id}-{app_config.stage}",
    app_config=app_config,
    pgstac_db=pgstac_stack.db,
)

# for key, value in {
#     "Project": app_config.project_id,
#     "Stage": app_config.stage,
#     "Owner": "hrodmn",
# }.items():
#     if value:
#         for stack in [vpc_stack, pgstac_stack, stactools_ingest_stack]:
#             Tags.of(stack).add(key, value)


app.synth()
