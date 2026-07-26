# Build context is the repo root (see docker-compose.yml) so this can COPY
# the sibling event-contracts package as a local dependency, same convention
# as every other service's Dockerfile.
#
# Unlike the FastAPI services, this image also needs a JVM (PySpark runs
# Spark's driver/executor inside a real JVM via py4j) and Spark's Kafka +
# S3A connector jars. Those jars are resolved from Maven once at *build*
# time (baked into the image layer) so no streaming job ever needs network
# access to a Maven repo at container-start time — see ADR 0005.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PATH="/usr/lib/jvm/java-17-openjdk-amd64/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      openjdk-17-jre-headless procps curl \
    && rm -rf /var/lib/apt/lists/* \
    && java -version

WORKDIR /app

COPY services/event-contracts /app/services/event-contracts
COPY services/data-platform/requirements.txt /app/services/data-platform/requirements.txt
RUN pip install --no-cache-dir --upgrade pip==26.1.2 \
    && pip install --no-cache-dir -r /app/services/data-platform/requirements.txt \
    && pip install --no-cache-dir -e /app/services/event-contracts

# Pre-fetch Spark's Kafka source connector and S3A/AWS SDK jars (and every
# transitive dependency Ivy resolves for them) into the image so a
# streaming job's SparkSession.builder never has to reach Maven Central at
# runtime. Versions are pinned to match pyspark==3.5.3 (Scala 2.12) and the
# hadoop-aws release that ships with it. Ivy resolves into /opt/ivy2/jars;
# those get copied straight into pyspark's own jars/ directory so every job
# picks them up automatically off the classpath with no `spark.jars.packages`
# (and therefore no network access) needed at container-start time.
RUN python -c "from pyspark.sql import SparkSession; \
SparkSession.builder \
  .config('spark.jars.packages', 'org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262') \
  .config('spark.jars.ivy', '/opt/ivy2') \
  .master('local[1]').getOrCreate().stop()" \
    && PYSPARK_JARS=$(python -c "import pyspark, os; print(os.path.join(os.path.dirname(pyspark.__file__), 'jars'))") \
    && cp /opt/ivy2/jars/*.jar "$PYSPARK_JARS"/ \
    && rm -rf /opt/ivy2

COPY services/data-platform /app/services/data-platform
WORKDIR /app/services/data-platform
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
