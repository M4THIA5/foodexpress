"""Accès RabbitMQ commun (SAGA + événements asynchrones).

Tous les événements métier transitent par un unique exchange **topic**
`foodexpress.events` ; le type d'événement est la *routing key* (architecture.md
§4.2). Ce module fournit les deux moitiés du transport asynchrone :

- `publish` : émission **best-effort** d'un événement (no-op si pas de broker) ;
- `start_consumer` : consommateur dans un thread démon, avec **reconnexion**
  automatique (le broker peut devenir disponible après le service — voir le
  commentaire `rabbitmq` du docker-compose).

La connexion n'est ouverte qu'à l'appel explicite (`get_connection`), jamais à
l'import.
"""
import json
import logging
import threading
from collections.abc import Callable, Iterable

import pika

from common.config import settings

logger = logging.getLogger(__name__)

# Exchange topic unique pour tous les événements métier FoodExpress.
EVENTS_EXCHANGE = "foodexpress.events"

# Délai avant nouvelle tentative de connexion du consommateur (broker indisponible).
_RECONNECT_DELAY = 5.0

# Handler applicatif d'un message consommé : (routing_key, payload décodé) -> None.
MessageHandler = Callable[[str, dict], None]


def get_connection() -> pika.BlockingConnection:
    if not settings.rabbitmq_url:
        raise RuntimeError("RABBITMQ_URL non configurée pour ce service")
    return pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))


def _declare_exchange(channel: pika.channel.Channel) -> None:
    channel.exchange_declare(
        exchange=EVENTS_EXCHANGE, exchange_type="topic", durable=True
    )


def publish(event_type: str, payload: dict) -> bool:
    """Publie un événement sur l'exchange. Renvoie True si émis, False sinon.

    **Best-effort** : le broker peut être indisponible (démarrage, panne). Un échec
    est journalisé sans lever d'exception — l'appelant (SAGA) poursuit. En l'absence
    de `RABBITMQ_URL` (tests, exécution isolée), c'est un no-op silencieux.
    """
    if not settings.rabbitmq_url:
        return False
    try:
        connection = get_connection()
        try:
            channel = connection.channel()
            _declare_exchange(channel)
            channel.basic_publish(
                exchange=EVENTS_EXCHANGE,
                routing_key=event_type,
                body=json.dumps(payload).encode(),
                properties=pika.BasicProperties(
                    content_type="application/json", delivery_mode=2
                ),
            )
        finally:
            connection.close()
        return True
    except Exception:  # broker indisponible : best-effort, on ne casse pas la SAGA
        logger.warning("Publication de %s échouée (broker indisponible)", event_type)
        return False


def start_consumer(
    queue: str, routing_keys: Iterable[str], handler: MessageHandler
) -> threading.Event | None:
    """Démarre un consommateur d'événements dans un thread démon.

    Déclare une `queue` durable liée à l'exchange topic pour chaque `routing_key`,
    puis appelle `handler(routing_key, payload)` sur chaque message décodé :
    - succès du handler → `ack` ;
    - handler qui lève / corps JSON illisible → `nack` **sans ré-enqueue** (pas de
      boucle de message empoisonné ; le prototype privilégie la simplicité).

    Reconnexion automatique tant que le broker est indisponible. Renvoie l'`Event`
    d'arrêt (appeler `.set()` pour stopper proprement au shutdown), ou `None` si
    aucun broker n'est configuré (tests, exécution isolée).
    """
    if not settings.rabbitmq_url:
        return None

    routing_keys = list(routing_keys)
    stop_event = threading.Event()

    def _on_message(channel, method, _properties, body) -> None:
        try:
            payload = json.loads(body)
        except ValueError:
            logger.warning("Message %s illisible, rejeté", method.routing_key)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        try:
            handler(method.routing_key, payload)
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            logger.exception(
                "Traitement de %s échoué, message rejeté", method.routing_key
            )
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _run() -> None:
        while not stop_event.is_set():
            try:
                connection = get_connection()
                channel = connection.channel()
                _declare_exchange(channel)
                channel.queue_declare(queue=queue, durable=True)
                for routing_key in routing_keys:
                    channel.queue_bind(queue, EVENTS_EXCHANGE, routing_key=routing_key)
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue, _on_message)
                logger.info("Consommateur '%s' à l'écoute de %s", queue, routing_keys)
                # Boucle courte pour pouvoir observer `stop_event` (arrêt propre).
                while not stop_event.is_set():
                    connection.process_data_events(time_limit=1)
                connection.close()
            except Exception:
                logger.warning(
                    "Consommateur '%s' déconnecté, reconnexion dans %ss",
                    queue, _RECONNECT_DELAY,
                )
                stop_event.wait(_RECONNECT_DELAY)

    threading.Thread(target=_run, name=f"consumer-{queue}", daemon=True).start()
    return stop_event
