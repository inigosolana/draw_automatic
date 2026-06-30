FROM alpine:3.19

RUN apk add --no-cache sqlite jq tzdata \
    && mkdir -p /var/log

COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /entrypoint.sh
COPY crontab /etc/crontabs/root

RUN chmod +x /usr/local/bin/backup.sh /entrypoint.sh \
    && chmod 600 /etc/crontabs/root

ENTRYPOINT ["/entrypoint.sh"]
