# Use the base image Alpine 3.16
FROM alpine:3.16

# Update packages and install dependencies
RUN apk upgrade --update-cache --available && \
    apk add python3 py3-pip git

# Set the working directory to /app
WORKDIR /app

# Copy the requirements file to the container
COPY requirements.txt /app/requirements.txt

# Install the requirements
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

# Copy cacert.pem from certifi to the appropriate location
RUN mkdir -p /etc/ssl/certs && \
    cp $(python3 -c 'import certifi; print(certifi.where())') /etc/ssl/certs/cacert.pem

# Execute commands directly in the container
CMD ["sh", "-c", "\
    export REQUESTS_CA_BUNDLE=/etc/ssl/certs/cacert.pem && \
    python3 /app/main.py list"]
