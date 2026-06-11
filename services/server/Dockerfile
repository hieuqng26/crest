# Stage 1: Builder — compile Python, install ODBC, install all Python packages
FROM registry.access.redhat.com/ubi9/ubi-minimal AS builder

WORKDIR /usr/src/app

RUN echo "sslverify=false" >> /etc/dnf/dnf.conf && \
    microdnf update -y && \
    microdnf install -y \
      gcc gcc-c++ findutils \
      openssl-devel bzip2-devel libffi-devel zlib-devel \
      wget make sqlite-devel xz-devel \
      pam tar bzip2 which file \
      autoconf automake libtool pkgconfig m4 \
      pcre2-devel cmake && \
    microdnf clean all

RUN cd /tmp && \
    wget --no-check-certificate --max-redirect=0 https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz && \
    tar xzf Python-3.11.9.tgz && \
    cd Python-3.11.9 && \
    ./configure --enable-optimizations --prefix=/usr/local && \
    make altinstall && \
    ln -sf /usr/local/bin/python3.11 /usr/local/bin/python3 && \
    ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip3 && \
    rm -rf /tmp/Python-3.11.9*

RUN mkdir -p /etc/pki/rpm-gpg && \
    curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/pki/rpm-gpg/microsoft.asc.gpg && \
    curl https://packages.microsoft.com/config/rhel/9/prod.repo -o /etc/yum.repos.d/mssql-release.repo && \
    microdnf update -y && \
    ACCEPT_EULA=Y microdnf install -y msodbcsql18 mssql-tools18 && \
    microdnf clean all

COPY requirements.txt /tmp/requirements.txt
RUN /usr/local/bin/pip3 install \
      --trusted-host pypi.org \
      --trusted-host pypi.python.org \
      --trusted-host files.pythonhosted.org \
      --upgrade pip setuptools build && \
    /usr/local/bin/pip3 install \
      --trusted-host pypi.org \
      --trusted-host pypi.python.org \
      --trusted-host files.pythonhosted.org \
      -r /tmp/requirements.txt \
      debugpy==1.8.5 werkzeug==2.2.2 && \
    rm /tmp/requirements.txt

# Stage 2: Runtime — minimal image, copy only compiled artifacts
FROM registry.access.redhat.com/ubi9/ubi-minimal AS runtime

WORKDIR /usr/src/app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH:/opt/mssql-tools18/bin" \
    LD_LIBRARY_PATH="/usr/local/lib" \
    PKG_CONFIG_PATH="/usr/local/lib/pkgconfig" \
    BOOST_ROOT=/usr/local

RUN echo "sslverify=false" >> /etc/dnf/dnf.conf && \
    microdnf update -y && \
    microdnf install -y \
      openssl bzip2 zlib sqlite libffi pam libstdc++ libgcc && \
    microdnf clean all

COPY --from=builder /usr/local /usr/local
COPY --from=builder /opt/mssql-tools18 /opt/mssql-tools18
COPY --from=builder /etc/pki/rpm-gpg /etc/pki/rpm-gpg
COPY --from=builder /etc/yum.repos.d/mssql-release.repo /etc/yum.repos.d/mssql-release.repo

RUN echo "sslverify=false" >> /etc/dnf/dnf.conf && \
    microdnf update -y && \
    ACCEPT_EULA=Y microdnf install -y msodbcsql18 && \
    microdnf clean all

RUN groupadd --system app && \
    useradd --system --home /usr/src/app --no-create-home --gid app app && \
    mkdir -p /home/app /var/lib/app_data /var/log/gunicorn && \
    chmod -R 775 /usr/src/app /var/log/gunicorn /var/lib/app_data /home/app

COPY manage.py requirements.txt gunicorn_config.py entrypoint.sh ./
COPY migrations/ ./migrations/
COPY project/ ./project/
COPY pyarmor_runtime_00640[2]/ ./pyarmor_runtime_006402/

RUN chmod +x entrypoint.sh && chown -R app:app /usr/src/app /var/log/gunicorn /var/lib/app_data /home/app

USER app

ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
