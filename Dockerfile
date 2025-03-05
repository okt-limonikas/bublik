###########################################
#         Base Python Image              #
###########################################
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/te/build/inst/default/bin:$PATH"

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
  gettext=0.21-12 \
  python3-celery=5.2.6-5 \
  rsync=3.2.7-1 \
  flex=2.6.4-8.2 \
  bison=2:3.8.2* \
  ninja-build=1.11.* \
  libjansson-dev=2.14-2 \
  libjansson-doc=2.14-2 \
  libjansson4=2.14-2 \
  libpopt-dev=1.19* \
  libpcre3-dev=2:8.39-15 \
  pixz=1.0.7-2 \
  libxml-parser-perl=2.46-4 \
  build-essential=12.9 \
  curl=7.88.1-10* \
  libkrb5-dev=1.20.1-2* \
  libffi-dev=3.4.4-1 \
  libxml2-dev=2.9.14* \
  libyaml-dev=0.2.5-1 \
  libssl-dev=3.0.15-1* \
  libglib2.0-dev=2.74.6-2* \
  git=1:2.39.5-0* \
  && rm -rf /var/lib/apt/lists/* \
  && cpan -T JSON

# Install UV
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN chmod +x /uv-installer.sh && /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
ENV UV_HTTP_TIMEOUT=2400

# Install dependencies using uv pip
RUN uv pip install --system --no-cache-dir meson==1.6.1 watchfiles==1.0.4

RUN mkdir bublik

COPY ./requirements.txt /app/bublik/requirements.txt
RUN uv pip install --system --no-cache-dir -r /app/bublik/requirements.txt

WORKDIR /app/te
COPY ./test-environment .
RUN ./dispatcher.sh -q --conf-builder=builder.conf.tools --no-run

###########################################
#         Documentation Builder          #
###########################################
FROM node:22.13-alpine AS docs-builder

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN npm i -g corepack@latest
RUN corepack enable

ARG URL_PREFIX
ARG DOCS_URL

WORKDIR /app

COPY ./bublik-release/package.json ./bublik-release/pnpm-lock.yaml ./

RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile

COPY ./bublik-release .

RUN URL="${DOCS_URL}" BASE_URL="${URL_PREFIX}/docs/" pnpm run build

###########################################
#           Bublik Runner               #
###########################################
FROM base AS runner

WORKDIR /app

COPY --from=docs-builder /app/build /app/bublik/docs

COPY . ./bublik

RUN mkdir -p bublik/logs && chmod +x ./bublik/entrypoint.sh

WORKDIR /app/bublik

###########################################
#           Log Server                    #
###########################################
FROM base AS log-server

RUN apt-get update && apt-get install -y \
    apache2 \
    file \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Enable CGI module
RUN a2enmod cgid

# Create necessary directories and set proper permissions
RUN mkdir -p \
    /home/te-logs/cgi-bin \
    /home/te-logs/logs \
    /home/te-logs/incoming \
    /home/te-logs/bad \
    && chown -R www-data:www-data /home/te-logs \
    && chmod -R 755 /home/te-logs

# Copy CGI scripts and templates
COPY ./test-environment/tools/log_server/te-logs-error404.template /home/te-logs/cgi-bin/te-logs-error404
COPY ./test-environment/tools/log_server/te-logs-index.template /home/te-logs/cgi-bin/te-logs-index
COPY ./test-environment/tools/log_server/publish-logs-unpack.sh /home/te-logs/bin/
COPY ./test-environment/tools/log_server/publish-incoming-logs.template /home/te-logs/bin/publish-incoming-logs

# Replace placeholders in CGI scripts and publish-incoming-logs
RUN sed -i \
    -e "s,@@TE_INSTALL@@,/app/te/build/inst,g" \
    -e "s,/srv/logs,/home/te-logs/logs,g" \
    -e "s,root_dir=\"/srv/logs\",root_dir=\"/home/te-logs/logs\",g" \
    -e "s,@@BUBLIK_URL@@,http://django:8000,g" \
    -e "s,@@LOGS_URL@@,http://te-log-server/logs,g" \
    -e "s,@@LOGS_DIR@@,/home/te-logs/logs,g" \
    -e "s,@@LOGS_INCOMING@@,/home/te-logs/incoming,g" \
    -e "s,@@LOGS_BAD@@,/home/te-logs/bad,g" \
    /home/te-logs/cgi-bin/te-logs-index \
    /home/te-logs/cgi-bin/te-logs-error404 \
    /app/te/build/inst/default/bin/te-logs-error404.sh \
    /app/te/build/inst/default/bin/te-logs-index.sh \
    /home/te-logs/bin/publish-incoming-logs

RUN chmod 750 /home/te-logs/cgi-bin/* /home/te-logs/bin/* \
    && echo "ServerName localhost" >> /etc/apache2/apache2.conf \
    && chown -R www-data:www-data /home/te-logs \
    && chmod -R 755 /home/te-logs/logs

COPY ./test-environment/tools/log_server/apache2-te-log-server.conf.template /etc/apache2/conf-available/te-logs.conf

RUN sed -i \
    -e "s,@@LOGS_CGI_BIN@@,/home/te-logs/cgi-bin,g" \
    -e "s,@@LOGS_DIR@@,/home/te-logs/logs,g" \
    -e "s,@@LOGS_URL_PATH@@,/logs,g" \
    /etc/apache2/conf-available/te-logs.conf

RUN a2enconf te-logs

# Configure Apache to log to stdout/stderr
RUN ln -sf /proc/self/fd/1 /var/log/apache2/access.log && \
    ln -sf /proc/self/fd/2 /var/log/apache2/error.log

# Update Apache configuration to use combined log format
RUN sed -i \
    -e 's|ErrorLog ${APACHE_LOG_DIR}/error.log|ErrorLog /proc/self/fd/2|' \
    -e 's|CustomLog ${APACHE_LOG_DIR}/access.log combined|CustomLog /proc/self/fd/1 combined|' \
    /etc/apache2/apache2.conf

EXPOSE 80

CMD ["apache2ctl", "-D", "FOREGROUND"]
