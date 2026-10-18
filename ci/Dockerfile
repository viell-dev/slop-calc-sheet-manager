FROM debian:13-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl python3 python3-pil xvfb xauth x11-utils xdotool dbus-x11 openbox fonts-dejavu-core \
    gdb \
    libgtk-3-0 libxtst6 libxinerama1 libxrender1 libxrandr2 libgl1 libglu1-mesa \
    libcups2 libdbus-glib-1-2 libsm6 libice6 libnss3 libxslt1.1 libx11-xcb1 libxcb-shm0 \
    && rm -rf /var/lib/apt/lists/*

ARG LO_VERSION
ARG LO_SERIES
ARG LO_URL
ARG LO_SHA256
RUN test -n "$LO_VERSION" && test -n "$LO_SERIES" && test -n "$LO_URL" && test -n "$LO_SHA256" \
    && curl --fail --location --retry 3 "$LO_URL" -o /tmp/libreoffice.tar.gz \
    && echo "$LO_SHA256  /tmp/libreoffice.tar.gz" | sha256sum --check --strict - \
    && mkdir /tmp/libreoffice /opt/ci-metadata \
    && tar -xzf /tmp/libreoffice.tar.gz -C /tmp/libreoffice \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/libreoffice/*/DEBS/*.deb \
    && ln -s "/opt/libreoffice$LO_SERIES" /opt/lo \
    && printf '%s\n%s\n%s\n' "$LO_VERSION" "$LO_URL" "$LO_SHA256" > /opt/ci-metadata/download.txt \
    && dpkg-query -W > /opt/ci-metadata/packages.tsv \
    && rm -rf /tmp/libreoffice /tmp/libreoffice.tar.gz /var/lib/apt/lists/*

ARG TEST_UID=1000
ARG TEST_GID=1000
RUN if ! getent group "$TEST_GID"; then groupadd --gid "$TEST_GID" tester; fi \
    && useradd --create-home --uid "$TEST_UID" --gid "$TEST_GID" tester

ENV LANG=C.UTF-8 GDK_BACKEND=x11 SAL_USE_VCLPLUGIN=gtk3
USER tester
WORKDIR /work
ENTRYPOINT ["/bin/bash", "/work/ci/linux-session.sh"]
