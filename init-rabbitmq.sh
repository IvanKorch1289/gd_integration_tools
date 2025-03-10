#!/bin/bash

# Ожидаем полный запуск RabbitMQ
until rabbitmqctl await_startup; do 
  sleep 1
done

# Создаем очереди, exchange и биндинги
rabbitmqadmin declare queue name=my_queue durable=true
rabbitmqadmin declare exchange name=my_exchange type=direct
rabbitmqadmin declare binding source=my_exchange destination=my_queue routing_key=my_routing_key

# Дополнительные настройки (пример для шардинга)
rabbitmqctl set_policy shard_policy "^sharded\." '{"shards-per-node":2}' --apply-to queues

# Включаем shovel (если нужно)
rabbitmqctl set_parameter shovel my-shovel '{"src-uri": "amqp://", "src-queue": "my_queue", "dest-uri": "amqp://", "dest-queue": "another_queue"}'