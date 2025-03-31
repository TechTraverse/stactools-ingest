from typing import Dict, Optional, Tuple, Type

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from typing_extensions import Self


class AppConfig(BaseSettings):
    project_id: str = Field(description="Project ID", default="stactools-uvx")
    stage: str = Field(description="Stage of deployment", default="test")
    tags: Optional[Dict[str, str]] = Field(
        description="""Tags to apply to resources. If none provided,
        will default to the defaults defined in `default_tags`.
        Note that if tags are passed to the CDK CLI via `--tags`,
        they will override any tags defined here.""",
        default=None,
    )
    data_access_role_arn: Optional[str] = Field(
        description="""Role ARN for data access that will be
        used by the API when reading assets in S3""",
        default=None,
    )
    acm_certificate_arn: Optional[str] = Field(
        description="""ARN of ACM certificate to use for
        custom domain names. If provided,
        CDNs are created for all the APIs""",
        default=None,
    )
    custom_domain: Optional[str] = Field(
        description="""Custom domain name for the STAC API.
        Must provide `acm_certificate_arn`""",
        default=None,
    )
    hosted_zone_id: Optional[str] = Field(
        description="Hosted Zone ID for custom domains",
        default=None,
    )
    hosted_zone_name: Optional[str] = Field(
        description="Hosted Zone Name for custom domains",
        default=None,
    )

    model_config = SettingsConfigDict(
        env_file=".env-cdk", yaml_file="config.yaml", extra="allow"
    )

    @field_validator("tags")
    def default_tags(cls, v, info: ValidationInfo):
        return v or {"project_id": info.data["project_id"], "stage": info.data["stage"]}

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        if self.acm_certificate_arn is None and self.custom_domain:
            raise ValueError(
                """If using a custom domain an ACM certificate ARN must be provided"""
            )

        return self

    def build_service_name(self, service_id: str) -> str:
        return f"{self.project_id}-{self.stage}-{service_id}"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
        )
