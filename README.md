# Infinity X 4.1 для POCO X8 Pro Max (`dash`)

Локально подготовленная конфигурация неофициального порта Android 17. Это **исходники и набор подготовки**, не готовая прошивка и не подтверждение успешной сборки или загрузки.

## Что подготовлено

- Снимок аппаратного дерева `xiaomi-mt6991/device_xiaomi_dash`, `cnb`, commit `574a0737bdc440ba90aa7b28681506ed28a44d9e`.
- Продукт `infinity_dash`, модель `2602BPC18G`, `UNOFFICIAL`, `userdebug`, первая сборка без GApps.
- 13 зависимостей, закреплённых по commit SHA в `sources/dependencies.json` и `local_manifests/dash.xml`.
- Проверяемый patch `patches/0001-infinity-dash.patch` для применения к оригинальному дереву после `repo sync`.
- Проверки pinned commits, повторного применения patch и защиты от перезаписи чужих изменений.
- Скрипты подготовки и сборки, не содержащие команд прошивки телефона.

## Проверка локального набора

```sh
python3 -m unittest discover -s tests -v
python3 tools/preflight.py
bash scripts/prepare-server.sh /srv/infinity-dash
```

Последняя команда по умолчанию только показывает план и не создаёт каталог исходников. Подготовка на сервере описана в [build/README.md](build/README.md).

## Состояние проверки

Проверены конфигурационные изменения, формат manifest, доступность выбранных refs и применение patch к ожидаемому исходному состоянию. Не выполнены полная синхронизация Android, сборка, финальная проверка бинарных ABI/VINTF, установка и аппаратные тесты.

Подробности исходников и ограничений: [sources/NOTES.md](sources/NOTES.md). План дальнейших этапов: [docs/superpowers/plans/2026-10-30-infinity-dash.md](docs/superpowers/plans/2026-10-30-infinity-dash.md).
