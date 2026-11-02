FROM node:24-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
ARG RELEASE_SHA=development
RUN npm run build && printf '{"release":"%s"}\n' "$RELEASE_SHA" > dist/release.json

FROM nginx:1.28-alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY deploy/nginx/site.conf /etc/nginx/snippets/site.conf
COPY deploy/nginx/http.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=DOMAIN
EXPOSE 80 443
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s CMD wget -qO- http://127.0.0.1/healthz || exit 1
