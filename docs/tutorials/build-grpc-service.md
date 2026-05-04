# Tutorial — Build a gRPC Service

Цель: добавить gRPC-action и сгенерировать `.proto`/pb2 через codegen.

## Что вы узнаете
- Как объявить action как `protocol="grpc"`.
- Как запустить compile-time codegen.
- Как протестировать через `grpcurl`.

## Шаги

1. Объявите action в `endpoints/*.py` — добавьте `transports=("grpc",)`.
2. Сгенерируйте proto + pb2:
   ```bash
   make grpc-codegen
   ```
3. Перезапустите backend.
4. Запрос:
   ```bash
   grpcurl -plaintext -d '{"name":"world"}' \
       localhost:50051 hello.HelloService/Greet
   ```

## Проверка
- `make grpc-codegen-dry` показывает план без записи.
- Файлы под `src/entrypoints/grpc/protobuf/` обновлены.
- gRPC-вызов отвечает.

## Next steps
- [REST connector](build-rest-connector.md)
- [DSL route](write-dsl-route.md)
