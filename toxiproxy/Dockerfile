# Toxiproxy et sa configuration, copiée dans l'image plutôt que montée : un volume
# dépend du système de fichiers de l'hôte (SELinux, partitions exFAT...).
FROM ghcr.io/shopify/toxiproxy:2.12.0
COPY toxiproxy.json /config/toxiproxy.json
CMD ["-host=0.0.0.0", "-config=/config/toxiproxy.json"]
