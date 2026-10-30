# Infinity X 4.1 для POCO X8 Pro Max (`dash`)

Конфигурация неофициального порта Android 17. Первая полная сборка запущена на выделенной VM. Это **исходники и набор подготовки**, не готовая прошивка и не подтверждение успешной сборки или загрузки.

## Что подготовлено

- Снимок аппаратного дерева `xiaomi-mt6991/device_xiaomi_dash`, `cnb`, commit `574a0737bdc440ba90aa7b28681506ed28a44d9e`.
- Продукт `infinity_dash`, модель `2602BPC18G`, `UNOFFICIAL`, `userdebug`, первая сборка без GApps.
- 13 зависимостей, закреплённых по commit SHA в `sources/dependencies.json` и `local_manifests/dash.xml`.
- Проверяемый patch `patches/0001-infinity-dash.patch` для применения к оригинальному дереву после `repo sync`.
- Проверки pinned commits, повторного применения patch и защиты от перезаписи чужих изменений.
- Скрипты подготовки и сборки, не содержащие команд прошивки телефона.
- Контроль доступа и целостности сборочного сервера с независимой сверкой на локальном ПК.
- Проверка SHA-256 всех входных файлов и запуск сборки из дерева, закрытого от записи; результаты и логи вынесены отдельно.

## Проверка локального набора

```sh
python3 -m unittest discover -s tests -v
python3 tools/preflight.py
bash scripts/prepare-server.sh /srv/infinity-dash
```

Последняя команда по умолчанию только показывает план и не создаёт каталог исходников. Подготовка на сервере описана в [build/README.md](build/README.md).

## Состояние проверки

Полная синхронизация Android завершена. Проверены закреплённые revisions, ожидаемые patches и полный снимок исходников; на сервере прошли `lunch infinity_dash cp2a userdebug`, `m nothing` и сборка `build-manifest.xml`. Полная сборка `m bacon -j8` перешла к компиляции, но ещё не завершена. Финальная проверка бинарных ABI/VINTF, установка и аппаратные тесты впереди.

GitHub Actions пока выключены; текущая сборка запущена через SSH. Компоненты будущего ограниченного интерфейса запуска описаны в [ci/README.md](ci/README.md).

Подробности исходников и ограничений: [sources/NOTES.md](sources/NOTES.md). План дальнейших этапов: [docs/superpowers/plans/2026-10-30-infinity-dash.md](docs/superpowers/plans/2026-10-30-infinity-dash.md).

После полной синхронизации зафиксированы конкретные revisions 1245 репозиториев: [build/source-manifest.xml](build/source-manifest.xml). Изменения для `dash` накладываются отдельным patch; manifest не заменяет проверку этих изменений и готовых образов.

## Авторство

Подготовка порта и инфраструктуры: [FeniksD](https://github.com/FeniksD). Аппаратное дерево основано на работе [xiaomi-mt6991](https://github.com/xiaomi-mt6991/device_xiaomi_dash), системная база — [Project Infinity X](https://github.com/ProjectInfinity-X). Авторство и лицензионные заголовки исходных файлов сохранены.

Проект демонстрирует адаптацию Android product/device-конфигурации, работу с Git/Repo, Linux, Python/Bash и проверками воспроизводимости. Статус подготовки не означает, что прошивка уже проверена на телефоне.
