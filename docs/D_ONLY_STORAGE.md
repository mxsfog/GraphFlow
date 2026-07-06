# Контроль хранения на диске D

## Локальные данные проекта

Runtime-данные OrientDB примонтированы в каталог проекта:

```text
D:\ElectroMotiv\.runtime\orientdb\databases
D:\ElectroMotiv\.runtime\orientdb\backup
```

Каталог `.runtime` не коммитится.

## Ограничение Docker

Слои Docker-образов и диск виртуальной машины Docker управляются Docker daemon. Compose-файл не может гарантировать их хранение на D.

## Проверка

```bash
docker info
docker system df
df -h .
```

Перед загрузкой образов нужно убедиться, что Docker Root Dir не расположен на системном диске C.
