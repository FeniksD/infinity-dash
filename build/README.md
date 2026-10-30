# Сборка на будущем сервере

## Машина

Рекомендуемый рабочий вариант: x86-64 AMD/Intel, Ubuntu 24.04, 64 ГБ RAM, 600 ГБ SSD/NVMe. Скрипт подготовки требует минимум 400 **GiB свободного места** до синхронизации. Количество параллельных задач задаётся отдельно; GPU не нужна.

Установить `git`, `git-lfs`, `repo`, `python3` и стандартные зависимости сборки Android. Официальный список: https://source.android.com/docs/setup/start/requirements . Для `repo` при отсутствии пакета в дистрибутиве: https://gerrit.googlesource.com/git-repo/+/HEAD/README.md . Выполнить `git lfs install` от имени сборочного пользователя.

Не запускать сборку от root. Каталог Android и каталог этого набора должны быть разными. Перенести весь набор на сервер, например в `~/infinity-dash-prep`; отдельный публичный GitHub-репозиторий для этого не требуется.

## 1. Проверить набор и команды

```sh
cd ~/infinity-dash-prep
python3 -m unittest discover -s tests -v
python3 tools/preflight.py
bash scripts/prepare-server.sh ~/android/infinity-dash
```

## 2. Скачать исходники и применить адаптацию

```sh
bash scripts/prepare-server.sh ~/android/infinity-dash --sync --jobs 8
```

Скрипт проверяет свободное место и инструменты, отказывается работать с чужим непустым каталогом, инициализирует pinned manifest Infinity, добавляет pinned `dash.xml`, выполняет `repo sync`, проверяет commits зависимостей и применяет patch только к ожидаемому чистому upstream-дереву. Повторно применённый patch распознаётся.

При ошибке sync или patch не использовать `--force-sync`, `git reset --hard` либо массовое удаление каталогов наугад. Сохранить вывод и исправить конкретную причину.

После sync сохраняется `.infinity-dash-logs/resolved-manifest.xml`. Верхний manifest и аппаратные зависимости закреплены заранее; остальные платформенные проекты могут ссылаться на ветки. Именно resolved manifest вместе с версией этого набора нужен для точного повторения состояния исходников.

## 3. Проверить checkout и собрать

```sh
python3 tools/preflight.py --source-root ~/android/infinity-dash
BUILD_JOBS=8 bash scripts/build-server.sh ~/android/infinity-dash
```

Скрипт выполняет `lunch infinity_dash cp2a userdebug` и `m bacon`. Здесь аргументы разделены пробелами: текущий парсер Infinity понимает вариант с дефисом как `product-variant`, поэтому `infinity_dash-cp2a-userdebug` ошибочно задаёт variant `cp2a-userdebug`. Общий пункт выбора зарегистрирован как `infinity_dash-userdebug`.

`cp2a` подтверждён в `vendor/infinity/vars/aosp_target_release` изученной ветки; `lunch` также выводит release из `build_id.mk`. Перед компиляцией скрипт проверяет фактически выбранные product, release и variant. Вывод подготовки окружения, `lunch` и самой сборки сохраняется в `.infinity-dash-logs/build-<UTC>-<PID>.log` внутри Android checkout; код ошибки сохраняется.

Результат ожидается в `out/target/product/dash/`. Завершение компиляции не подтверждает исправность камеры, модема, отпечатка, сна и зарядки; перед установкой нужен отдельный разбор образов и сценария восстановления. Скрипт сборки не устанавливает результат.

## Что не проверено на этой машине

Этот набор подготовлен на ПК с 16 ГБ RAM и примерно 75 ГБ свободного места. Полный `repo sync`, `lunch` в собранном дереве и `m bacon` локально не запускались. Возможные несовместимости приватных/аппаратных API будут разбираться по настоящим логам сборки, а не скрываться флагом `ALLOW_MISSING_DEPENDENCIES`.

Восстановление закреплённых версий на новой VM, сохранение промежуточных результатов и план prerelease-публикации описаны в [MIGRATION.md](MIGRATION.md).
