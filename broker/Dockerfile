# Mosquitto with the go-auth plugin. Authentication and topic ACLs are
# delegated to the Ovian server over HTTP (see server modules/mqtt_auth.py).
FROM iegomez/mosquitto-go-auth:3.0.0-mosquitto_2.0.18
COPY mosquitto.conf.template entrypoint.sh /mosquitto/ovian/
EXPOSE 1883 9001
ENTRYPOINT ["/usr/bin/tini", "--", "/mosquitto/ovian/entrypoint.sh"]
