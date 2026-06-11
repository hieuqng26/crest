FROM registry.access.redhat.com/ubi9/nodejs-22-minimal AS build-stage

# Set the work directory
WORKDIR /app

# Switch to root user to fix permissions
USER root

# Copy package.json and package-lock.json
COPY package*.json ./

# Install dependencies
RUN npm install --ignore-scripts

# SAST doesn't like COPY . .
COPY .env .
COPY default.conf.template .
COPY Dockerfile .
COPY index.html .
COPY jsconfig.json .
COPY package.json .
COPY package-lock.json .
COPY postcss.config.js .
COPY tailwind.config.js .
COPY vite.config.js .
COPY public/ ./public/
COPY src/ ./src/
COPY css/ ./css/
COPY ssl/ ./ssl/

RUN npm run build

# production stage
FROM registry.access.redhat.com/ubi9/nginx-126 AS production-stage

# Create a non-root user and group
ENV NGINX_USER=nginx
ENV NGINX_GROUP=nginx
RUN getent group $NGINX_GROUP || groupadd -r $NGINX_GROUP && \
    getent passwd $NGINX_USER || useradd -r -g $NGINX_GROUP $NGINX_USER

# Create necessary directories and set permissions
USER root
RUN mkdir -p /usr/share/nginx/html /etc/nginx/templates /etc/nginx /var/log/nginx /var/cache/nginx /var/run/nginx /var/lib/nginx /run /opt/app-root/etc/nginx.d/ && \
    chown -R $NGINX_USER:$NGINX_GROUP /usr/share/nginx/html /etc/nginx/templates /etc/nginx /var/log/nginx /var/cache/nginx /var/run/nginx /var/lib/nginx /run /opt/app-root/etc/nginx.d/ && \
    chmod -R 755 /usr/share/nginx/html /etc/nginx/templates /etc/nginx /var/log/nginx /var/cache/nginx /var/run/nginx /var/lib/nginx /run /opt/app-root/etc/nginx.d/

# Update packages and completely remove Python3.9
RUN dnf update -y && \
    dnf install -y \
    net-tools \
    pam && \
    # Completely remove Python3.9 and all related packages
    dnf remove -y python39* python3.9* platform-python* python3-pip || true && \
    # Clean up
    dnf clean all && \
    # Remove any remaining Python3.9 binaries and directories
    rm -f /usr/bin/python3.9* && \
    rm -rf /usr/lib/python3.9* /usr/lib64/python3.9* /usr/local/lib/python3.9* /usr/include/python3.9* /usr/share/doc/python3.9* /usr/share/man/man1/python3.9*

# Copy built files and configuration
COPY --from=build-stage /app/dist /usr/share/nginx/html
COPY default.conf.template ./
COPY nginx.conf /etc/nginx/nginx.conf

RUN sed -i 's/https:\/\/github.com\/crypto\-browserify\/crypto\-browserify//g' /usr/share/nginx/html/assets/`ls /usr/share/nginx/html/assets | grep -E index.+\.js`

# Switch to the non-root user
USER $NGINX_USER

# Expose the port
EXPOSE $PORT

# Run nginx
CMD ["nginx", "-g", "daemon off;"]