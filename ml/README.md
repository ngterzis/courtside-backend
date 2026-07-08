# Offline ML pipeline — next-game points

Trains and ships the model that powers `GET /api/me/projection`. Feature logic is
imported from `courtside.ml` (the package in the Lambda image) so training and serving
never diverge. Heavy deps live in the `ml` uv group and never enter the serving image.

```
ml/
  config.py                 # env-driven pipeline config (region, feature group, S3, role, MLflow)
  pipeline.py                # SageMaker Pipeline DAG (ingest → prepare → train → evaluate → register) + CLI
  feature_store/
    feature_group.py        # create/describe the SageMaker feature group (schema ← FEATURE_NAMES)
    ingest.py               # games → point-in-time feature records → PutRecord (online + offline)
    training_query.sql      # dedup-to-latest, leak-free training set from the offline store
  training/
    prepare_data.py         # Athena → time-split → train.csv/test.csv (Processing step)
    train_script.py         # XGBoost script-mode entry point, run inside the Training step
    evaluate.py              # extracts model_mae/baseline_mae from model.tar.gz (Processing step)
  serving/
    inference.py            # SageMaker XGBoost script-mode handlers (CSV in → points out)
    deploy_endpoint.py      # latest Approved package → Serverless Inference endpoint
```

Ingest, PrepareData and Evaluate run on the image built from `Dockerfile.ml` (pushed to
a dedicated ECR repo by `.github/workflows/ml-pipeline.yml` on every push touching
`ml/**`). Train reuses the built-in SageMaker XGBoost container via `train_script.py`,
same as before.

## One-time setup

The feature group, model package group, managed MLflow server, S3 bucket, SageMaker
execution role, and the pipeline's ECR repo are all provisioned by the `ml` module in
the **courtside-infra** repo. Pull the config from its Terraform outputs:

```bash
uv sync --group ml
export AWS_REGION=eu-central-1
export FEATURE_GROUP_NAME=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_feature_group_name)
export FEATURE_STORE_OFFLINE_S3=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_offline_store_s3)
export ATHENA_OUTPUT_S3=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_athena_output_s3)
export SAGEMAKER_ROLE_ARN=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_sagemaker_role_arn)
export MODEL_PACKAGE_GROUP=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_model_package_group)
export ENDPOINT_NAME=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_endpoint_name)
export MLFLOW_TRACKING_URI=$(terraform -chdir=../courtside-infra/envs/prod output -raw mlflow_tracking_server_arn)
export PIPELINE_NAME=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_pipeline_name)
export ML_PIPELINE_IMAGE_URI=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_pipeline_repository_url):latest
# Only needed for `ml.pipeline upsert` (the Ingest step reads Postgres via the Data API):
export DB_CLUSTER_ARN=$(terraform -chdir=../courtside-infra/envs/prod output -raw db_cluster_arn)
export DB_SECRET_ARN=$(terraform -chdir=../courtside-infra/envs/prod output -raw db_credentials_secret_arn)
```

> The feature group is Terraform-owned, so `ml.feature_store.feature_group` is
> describe/verify only in prod (`... feature_group describe`). Its schema mirrors
> `courtside.ml.features.FEATURE_NAMES`, which must stay in sync with the
> `ml_feature_names` list in `courtside-infra/envs/prod/main.tf`.

## Each run of the loop

CI (`.github/workflows/ml-pipeline.yml`) keeps the pipeline definition in sync with this
code on every push — it never starts a run. Runs are on-demand only:

```bash
uv run --group ml python -m ml.pipeline run   # or: aws sagemaker start-pipeline-execution --pipeline-name "$PIPELINE_NAME"
# ingest → prepare data → train → evaluate → (if it beats baseline) register as PendingManualApproval
# then, once you've approved the model package in the SageMaker console:
uv run --group ml python -m ml.serving.deploy_endpoint     # ship to the Serverless endpoint
```

Point the API at the endpoint by setting `SAGEMAKER_ENDPOINT_NAME` (and
`FEATURE_GROUP_NAME`) on the Lambda; until then the endpoint is unset and
`/api/me/projection` returns the trailing-average baseline.

## Cost

The Serverless endpoint scales to zero, and pipeline steps only run (and cost anything)
while a manually-started execution is in progress. The Feature Store online store and
the managed MLflow server are the small standing costs — delete the feature group and
endpoint when you're done experimenting.
