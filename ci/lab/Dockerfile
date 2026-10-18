ARG BASE
FROM ${BASE}
ARG GDBTRACE=gdbtrace
USER root
COPY ${GDBTRACE} /tmp/lab-gdbtrace
RUN cp /tmp/lab-gdbtrace "$(readlink -f /opt/lo)/program/gdbtrace" && rm /tmp/lab-gdbtrace
USER tester
