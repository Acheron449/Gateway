# Multi-stage build for React + Vite frontend
# Stage 1: Build
FROM node:20-alpine as builder

WORKDIR /build

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install --prefer-offline --force

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

# Stage 2: Serve
FROM node:20-alpine

WORKDIR /app

# Install serve to run the static build
RUN npm install -g serve

# Create non-root user
RUN addgroup -g 1001 appuser && adduser -D -u 1001 -G appuser appuser

# Copy built assets from builder
COPY --from=builder --chown=appuser:appuser /build/dist ./dist

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000 || exit 1

# Serve static files
CMD ["serve", "-s", "dist", "-l", "3000"]
