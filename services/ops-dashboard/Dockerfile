# Build context is the repo root (see docker-compose.yml), matching every
# other service's Dockerfile convention — though this one has no sibling
# local package to copy in.
FROM node:22-alpine AS build
WORKDIR /app
COPY services/ops-dashboard/package.json services/ops-dashboard/package-lock.json ./
RUN npm ci
COPY services/ops-dashboard ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY services/ops-dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY services/ops-dashboard/proxy_params.conf /etc/nginx/proxy_params.conf

EXPOSE 80
# 127.0.0.1, not localhost: nginx.conf's `listen 80;` only binds IPv4, but
# this image's musl/busybox wget resolves "localhost" to ::1 (IPv6) first —
# found by hitting a real, otherwise-inexplicable "unhealthy" status
# against a fully working container (every proxied route serving real
# traffic correctly the whole time; only the healthcheck itself was
# querying the wrong address family).
HEALTHCHECK --interval=5s --timeout=5s --retries=10 \
    CMD wget -qO- http://127.0.0.1:80 >/dev/null 2>&1 || exit 1
