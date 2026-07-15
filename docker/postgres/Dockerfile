FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates git postgresql-server-dev-16 \
    && git clone --depth 1 --branch v0.8.1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector \
    && make -C /tmp/pgvector install \
    && rm -rf /tmp/pgvector /var/lib/apt/lists/*
