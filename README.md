# stactools-uvx

A FastAPI service that dynamically loads and executes [stactools](https://github.com/stactools-packages) packages using [uvx](https://docs.astral.sh/uv/guides/tools/) to create STAC items.

## Overview

stactools-uvx provides a FastAPI app that allows you to:

1. Dynamically install any `stactools` package on-demand
2. Execute the package's CLI commands to create STAC items
3. Return the resulting STAC item as a JSON response

This approach eliminates the need to pre-install all possible stactools packages, allowing for a more flexible and maintainable service architecture.

## How It Works

The service uses `uvx` (the execution engine for the `uv` Python package manager) to:

1. Create an isolated environment for each request
2. Install the requested stactools package
3. Execute the package's CLI commands
4. Return the resulting STAC metadata

## API Usage

### Create a STAC Item

**Endpoint**: `POST /item`

**Request Body**:

```json
{
  "package_name": "stactools-glad-glclu2020",
  "group_name": "gladglclu2020",
  "create_item_args": [
    "https://storage.googleapis.com/earthenginepartners-hansen/GLCLU2000-2020/v2/2000/50N_090W.tif"
  ],
  "create_item_options": {
    "option1": "value1"
  },
  "collection_id": "optional-collection-id"
}
```

**Parameters**:

- `package_name`: The name of the stactools package to use (e.g., `stactools-glad-glclu2020`)
- `group_name`: The group name for the STAC item (used in the CLI command)
- `create_item_args`: List of positional arguments for the `create-item` command
- `create_item_options`: (Optional) Dictionary of CLI options for the `create-item` command
- `collection_id`: (Optional) Value for the collection field of the item JSON

**Response**: A STAC Item JSON

## Local Development

### Prerequisites

- [uv](https://github.com/astral-sh/uv)

### Setup

```bash
git clone https://github.com/developmentseed/stactools-uvx.git
cd stactools-uvx

uv sync
```

### Running the Server

```bash
uv run src/stactools_uvx/app.py
```

### Testing

Run the unit tests with:

```bash
uv run pytest
```

The service will be available at <http://localhost:8000>. API documentation is available at <http://localhost:8000/docs>.

## Deployment

This repository includes an AWS CDK app for deploying the service to AWS.

### Prerequisites for Deployment

- AWS CLI configured with appropriate credentials
- AWS CDK installed
- Docker (for building container images)

### Populate `config.yaml`

```yaml
project_id: 'stactools-uvx'
stage: 'dev'
tags:
  Project: 'stactools-uvx'
  Stage: 'dev'
  Owner: <username>

# optional custom domain configuration
acm_certificate_arn: <certificate arn>
custom_domain: <custom domain>

hosted_zone_name: <hosted zone name>
hosted_zone_id: <hosted zone id>

```

### Deploy to AWS

```bash
npm install
uv sync --all-groups
AWS_DEFAULT_REGION=us-west-2 uv run cdk deploy
```

## Architecture

The app will be deployed in a Lambda function based on a Docker image with the `stactools_uvx` package installed and some of the`stactools` packages and dependencies loaded into the `uv-cache`.

- Lambda Function
- CloudWatch Logs
- API Gateway Endpoint
  - optionally routed to a custom domain name with a Route 53 alias record for a hosted zone
