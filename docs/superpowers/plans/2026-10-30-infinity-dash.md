# Infinity X dash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Получить проверяемую неофициальную сборку Infinity X 4.1 / Android 17 для POCO X8 Pro Max (`dash`).

**Architecture:** Сохранить существующую аппаратную реализацию `dash/cnb`, адаптировать product-конфигурацию к Infinity, зафиксировать доступные device/vendor/kernel/hardware зависимости. Выполнить полную сборку после выбора подходящего хранилища, затем отдельно проверить образы и аппаратную работоспособность.

**Tech Stack:** Android Repo, Git, Android build/Soong/Make, XML manifests, существующее prebuilt ядро и vendor blobs.

**Spec:** `docs/superpowers/specs/2026-10-30-infinity-dash-design.md`

## Global Constraints

- Target: `2602BPC18G`, `dash`, MT6991; Infinity ветка `17`.
- Первая сборка: `UNOFFICIAL`, `userdebug`, Vanilla.
- Не использовать чужие приватные ключи подписи, keybox или персональные NV-данные.
- Не смешивать несогласованные kernel/DTB/modules; не менять vendor fingerprints без технической причины.
- До отдельного этапа испытаний не изменять разделы телефона.
- Оплачиваемые ресурсы не создавать без бюджета пользователя.

## Review Focus

- Ветка `cnb` отсутствует у части зависимостей: выбирать другую ветку только после проверки её интерфейсов и истории.
- `bka` manifest содержит чужие Evo keys и replace/remove правила: переносить только нужные зависимости.
- Необязательная MiCam может требовать отдельных blobs и patches: выявить до сборки, не скрывать ошибку missing dependencies.
- A/B и dynamic partitions: проверять размеры и согласованность загрузочных образов, не считать второй слот независимым dual boot.
- Достаточная ёмкость диска и RAM: не начинать большой sync, пока место для исходников и результатов не выделено.

---

### Task 1: Зафиксировать аппаратную базу

**Files:**
- Create: `sources/dependencies.json`
- Create: `local_manifests/dash.xml`
- Reference: upstream `device/xiaomi/dash/{AndroidProducts.mk,lineage_dash.mk,device.mk,BoardConfig.mk}`

**Interfaces:**
- Consumes: изученный `dash/cnb` commit и upstream `bka` manifest.
- Produces: список `path`, `remote`, `repository`, `branch`, `commit` для каждой выбранной зависимости и manifest без приватных ключей.

- [ ] Прочитать прямые includes/inherit-product аппаратного дерева и составить полный список внешних путей.
- [ ] Проверить доступные refs каждого репозитория; записать выбранный commit и причину выбора ветки.
- [ ] Создать manifest с уникальными путями; проверить его XML-парсером и сверить replace/remove правила с Infinity manifest.
- [ ] Проверить, что каждый обязательный путь из includes обеспечен manifest или базовой Infinity.

### Task 2: Адаптировать product-конфигурацию

**Files:**
- Create: `device/xiaomi/dash/infinity_dash.mk`
- Modify: `device/xiaomi/dash/AndroidProducts.mk`
- Modify as required: `device/xiaomi/dash/BoardConfig.mk`
- Reference: `device/xiaomi/dash/evolution.mk`

**Interfaces:**
- Consumes: зависимости Task 1 и настоящий интерфейс `vendor/infinity` ветки `17`.
- Produces: распознаваемый сборочной системой продукт `infinity_dash` без подключения Evo product branding/keys.

- [ ] Сопоставить настройки `lineage_dash.mk` и `evolution.mk` с Infinity; отдельно сохранить необходимые аппаратные опции.
- [ ] Подключить `vendor/infinity/config/common_full_phone.mk`, сохранить аппаратную идентичность, задать техническую Vanilla/UNOFFICIAL конфигурацию.
- [ ] Зарегистрировать продукт в `AndroidProducts.mk`; исправить только несовместимые build includes.
- [ ] После синхронизации проверить продукт через `lunch` с release-config, фактически объявленным текущей Infinity; не копировать старую команду `lunch` без проверки.

### Task 3: Подготовить сборочную машину и собрать

**Files:**
- Create: `build/README.md`
- Create: `build/source-manifest.xml` из `repo manifest -r`
- Preserve: `logs/build.log`

**Interfaces:**
- Consumes: Tasks 1–2 и выделенное пользователем рабочее хранилище/сборочная машина.
- Produces: полный build log, pinned manifest и build artifacts для `dash`.

- [ ] Проверить свободное место, ОС, RAM и инструменты; записать рабочий каталог и ограничения параллелизма.
- [ ] Синхронизировать Infinity и выбранные зависимости, сохранить resolved manifest.
- [ ] До компиляции проверить commits и локальные изменения; root создаёт read-only bind mount дерева, отдельные writable output/log paths. Проверить отказ записи от UID сборщика.
- [ ] Создать `security/source_lock.py`: потоковый SHA-256 manifest всех файлов/ссылок дерева (без `.repo`, `.git`, `out`, `.infinity-dash-logs`), проверка добавлений/удалений/изменений, отказ на внешних ссылках и hardlinks. Тесты должны сначала показать отсутствие реализации, затем принять точный снимок и отклонить подмену, добавленный файл и escaping symlink.
- [ ] Создать `security/build_guarded.sh`: обязательная проверка read-only mount и полного снимка до/после сборки, отдельный `OUT_DIR`, сохранение exit code и логов. Проверить, что несверенное/доступное для записи дерево не запускает компиляцию.
- [ ] Скопировать эталон на локальный ПК; добавить наблюдение read-only mount в серверный контроль. Не создавать новые эталоны автоматически при несоответствии.
- [ ] Проверить `lunch`/dumpvars и запустить штатную цель сборки Infinity, сохраняя полный вывод и exit code.
- [ ] При ошибках исправлять по одной причине; повторять относящуюся к ней проверку и сборку.

### Task 4: Проверить выходные образы

**Files:**
- Create: `artifacts/SHA256SUMS`
- Create: `artifacts/image-checks.json`
- Preserve: VINTF/AVB/partition validation logs

**Interfaces:**
- Consumes: artifacts Task 3 и фактическая схема разделов `dash`.
- Produces: перечень проверок с результатами и явными непроверенными свойствами.

- [ ] Проверить целевую модель, размеры разделов, структуру boot/init_boot/vendor_boot/DTB и версии kernel/modules.
- [ ] Выполнить применимые проверки VINTF, AVB и содержимого OTA; записать результаты и SHA-256.
- [ ] Проверить сценарий установки и восстановления; исключить неожиданные записи firmware/NV и relock.

### Task 5: Аппаратные испытания

**Files:**
- Create: `validation/device-checklist.md`
- Preserve: относящиеся к сбою logcat/kernel logs без публикации персональных данных

**Interfaces:**
- Consumes: Task 4, отдельное согласование установки и актуальные резервные копии пользователя.
- Produces: результаты первой загрузки и матрица аппаратных функций с воспроизводимыми сбоями.

- [ ] Перед установкой подтвердить текущую модель/слот, резервные копии и доступный путь восстановления.
- [ ] Проверить первую загрузку и recovery; не считать успешное отображение рабочего стола полной проверкой.
- [ ] Проверить связь, экран/тач, звук, камеры, отпечаток, зарядку и сон/пробуждение.
- [ ] Провести повторяемый замер расхода в простое, сравнить с исходной системой и явно описать условия.
- [ ] Исправлять подтверждённые проблемы по одной; повседневную готовность объявлять только по результатам испытаний.
