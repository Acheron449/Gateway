# Multi-stage build for React + Vite frontend
# Stage 1: Build
FROM node:20-alpine as builder

WORKDIR /build

# Copy package files
COPY package.json package-lock.json ./

# Install exactly the versions recorded in package-lock.json
RUN npm ci

# Copy source files
COPY src ./src
COPY tsconfig.json tailwind.config.js vite.config.ts index.html ./

# Auth0 SPA config — Vite bakes VITE_* vars at build time, so they must be
# build args (compose passes them through from the host .env). Empty values
# keep the image working with local password auth only.
ARG VITE_AUTH0_DOMAIN
ARG VITE_AUTH0_CLIENT_ID
ARG VITE_AUTH0_AUDIENCE
ENV VITE_AUTH0_DOMAIN=${VITE_AUTH0_DOMAIN} \
    VITE_AUTH0_CLIENT_ID=${VITE_AUTH0_CLIENT_ID} \
    VITE_AUTH0_AUDIENCE=${VITE_AUTH0_AUDIENCE}

# Build
RUN npm run build

# Stage 2: Serve static assets as a non-root user without a Node runtime
FROM nginxinc/nginx-unprivileged:1.30.5-alpine3.24

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist/ /usr/share/nginx/html/

# Keep the Compose service port unchanged and retain SPA history fallback.
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1
