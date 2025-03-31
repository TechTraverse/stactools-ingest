import os

from aws_cdk import (
    App,
    CfnOutput,
    Duration,
    Stack,
    Tags,
    aws_apigatewayv2,
    aws_apigatewayv2_integrations,
    aws_certificatemanager,
    aws_iam,
    aws_lambda,
    aws_logs,
    aws_route53,
    aws_route53_targets,
)
from aws_cdk.aws_ecr_assets import Platform
from config import AppConfig
from constructs import Construct


class StactoolsUvxStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        app_config: AppConfig,
        context_dir: str = "./",
        runtime: aws_lambda.Runtime = aws_lambda.Runtime.PYTHON_3_11,
        **kwargs,
    ) -> None:
        super().__init__(
            scope,
            id=id,
            tags=app_config.tags,
            **kwargs,
        )

        lambda_function = aws_lambda.DockerImageFunction(
            self,
            "lambda",
            code=aws_lambda.DockerImageCode.from_image_asset(
                directory=os.path.abspath(context_dir),
                file="infrastructure/Dockerfile",
                platform=Platform.LINUX_AMD64,
                build_args={
                    "PYTHON_VERSION": runtime.to_string().replace("python", ""),
                },
            ),
            memory_size=1024,
            timeout=Duration.seconds(15),
            log_retention=aws_logs.RetentionDays.ONE_WEEK,
            role=aws_iam.Role.from_role_arn(
                self,
                "reader-role",
                role_arn=app_config.data_access_role_arn,
            )
            if app_config.data_access_role_arn
            else None,
        )

        domain_name = None
        if app_config.acm_certificate_arn and app_config.custom_domain:
            domain_name = aws_apigatewayv2.DomainName(
                self,
                "custom-domain",
                domain_name=app_config.custom_domain,
                certificate=aws_certificatemanager.Certificate.from_certificate_arn(
                    self,
                    "raster-api-cdn-certificate",
                    certificate_arn=app_config.acm_certificate_arn,
                ),
            )

            if app_config.hosted_zone_id and app_config.hosted_zone_name:
                hosted_zone = aws_route53.HostedZone.from_hosted_zone_attributes(
                    self,
                    "hosted-zone",
                    hosted_zone_id=app_config.hosted_zone_id,
                    zone_name=app_config.hosted_zone_name,
                )

                aws_route53.ARecord(
                    self,
                    "CustomDomainAliasRecord",
                    zone=hosted_zone,
                    record_name=app_config.custom_domain,
                    target=aws_route53.RecordTarget.from_alias(
                        aws_route53_targets.ApiGatewayv2DomainProperties(
                            domain_name.regional_domain_name,
                            domain_name.regional_hosted_zone_id,
                        )
                    ),
                )

        api = aws_apigatewayv2.HttpApi(
            self,
            "api",
            default_integration=aws_apigatewayv2_integrations.HttpLambdaIntegration(
                "api-integration",
                lambda_function,
                parameter_mapping=aws_apigatewayv2.ParameterMapping().overwrite_header(
                    "host",
                    aws_apigatewayv2.MappingValue.custom(app_config.custom_domain),
                )
                if app_config.custom_domain
                else None,
            ),
            default_domain_mapping={"domain_name": domain_name}
            if domain_name
            else None,
        )

        assert api.url
        CfnOutput(self, "api-url", value=api.url)


app = App()

app_config = AppConfig()

stactools_uvx_stack = StactoolsUvxStack(
    app,
    f"{app_config.project_id}-{app_config.stage}",
    app_config=app_config,
)

for key, value in {
    "Project": app_config.project_id,
    "Stage": app_config.stage,
    "Owner": "hrodmn",
}.items():
    if value:
        Tags.of(stactools_uvx_stack).add(key, value)


app.synth()
