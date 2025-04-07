from typing import Dict, Optional, Tuple, Type

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class AppConfig(BaseSettings):
    project_id: str = Field(description="Project ID", default="stactools-ingest")
    stage: str = Field(description="Stage of deployment", default="test")
    tags: Optional[Dict[str, str]] = Field(
        description="""Tags to apply to resources. If none provided,
        will default to the defaults defined in `default_tags`.
        Note that if tags are passed to the CDK CLI via `--tags`,
        they will override any tags defined here.""",
        default=None,
    )

    nat_gateway_count: int = Field(
        description="Number of NAT gateways to create",
        default=0,
    )
    db_instance_type: str = Field(
        description="Database instance type", default="t3.micro"
    )
    db_allocated_storage: int = Field(
        description="Allocated storage for the database", default=5
    )

    model_config = SettingsConfigDict(
        env_file=".env-cdk", yaml_file="config.yaml", extra="allow"
    )

    @field_validator("tags")
    def default_tags(cls, v, info: ValidationInfo):
        return v or {"project_id": info.data["project_id"], "stage": info.data["stage"]}

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
