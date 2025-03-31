import json
import logging
import subprocess
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from stac_pydantic.item import Item

logger = logging.getLogger()
logger.setLevel(logging.INFO)

app = FastAPI(
    title="stactools-uvx",
    version="0.1.0",
    openapi_url="/api",
    docs_url="/docs",
)


class StactoolsRequest(BaseModel):
    package_name: str = Field(..., description="Name of the stactools package")
    group_name: str = Field(..., description="Group name for the STAC item")
    create_item_args: List[str] = Field(
        ..., description="Arguments for create-item command"
    )
    create_item_options: Dict[str, str] = Field(
        default_factory=dict, description="Options for create-item command"
    )
    collection_id: Optional[str] = Field(
        None, description="value for the collection field of the item json"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "package_name": "stactools-glad-glclu2020",
                "group_name": "gladglclu2020",
                "create_item_args": [
                    "https://storage.googleapis.com/earthenginepartners-hansen/GLCLU2000-2020/v2/2000/50N_090W.tif"
                ],
            }
        }
    )


@app.post("/item", response_model=Item, response_model_exclude_none=True)
async def create_stac_item(request: StactoolsRequest):
    """
    Create a STAC item using a stactools package
    """
    logger.info(f"Received request: {json.dumps(request.model_dump())}")

    if not request.package_name:
        raise HTTPException(
            status_code=400, detail="Missing required parameter: package_name"
        )

    command = [
        "uvx",
        "--with",
        f"requests,{request.package_name}",
        "--from",
        "stactools",
        "stac",
        request.group_name,
        "create-item",
        *request.create_item_args,
    ]

    for option, value in request.create_item_options.items():
        command.extend([f"--{option}", value])

    logger.info(f"Executing command: {' '.join(command)}")

    try:
        with NamedTemporaryFile(suffix=".json") as output:
            command.append(output.name)
            result = subprocess.run(command, capture_output=True, text=True, check=True)

            logger.info(f"Command output: {result.stdout}")
            with open(output.name) as f:
                item_dict = json.load(f)

        if request.collection_id:
            item_dict["collection"] = request.collection_id

        return Item(**item_dict)

    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e}")
        logger.error(f"Stderr: {e.stderr}")

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Command execution failed",
                "stderr": e.stderr,
                "stdout": e.stdout if hasattr(e, "stdout") else "",
            },
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
