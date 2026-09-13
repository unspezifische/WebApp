# Dockerfile for React app with Nginx
FROM node:18-alpine AS build

# Set the working directory
WORKDIR /app

# INCREASE NODE MEMORY LIMIT HERE (4096 = 4GB, 6144 = 6GB)
ENV NODE_OPTIONS="--max-old-space-size=6144"

# CRITICAL: Disable source maps to save massive amounts of RAM during build
ENV GENERATE_SOURCEMAP=false

# Copy package.json and install dependencies (paths are relative to build context)
COPY webapp/package*.json ./

# Install the specific version of npm
RUN npm install -g npm@10.8.3

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY webapp/. ./

# Build the React app
RUN npm run build

# Stage 2: Nginx
FROM nginx:alpine

# Copy the build output to Nginx's html directory
COPY --from=build /app/build /usr/share/nginx/html

# Copy the standalone 5etools static site to a directory the nginx config expects
# This requires docker build context to include the project root (handled in docker-compose)
COPY 5etools-src /var/www/5etools

# Copy the custom Nginx configuration file (path is relative to build context)
COPY webapp/nginx-docker.conf /etc/nginx/nginx.conf

# Expose the port Nginx will listen on
EXPOSE 80