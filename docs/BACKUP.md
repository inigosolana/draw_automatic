# Copias de seguridad y restauración

## Qué se respalda

El contenedor `backup` (servicio `backup` del `docker-compose.yml`) hace una copia
diaria con `sqlite3 .backup` de las 5 bases de datos de la app, desde el volumen
`draw_automatic_drawio_data` al volumen `draw_automatic_drawio_backup`:

`downloads`, `sites`, `catalog`, `activity`, `security`.

Retención: `DRAWIO_BACKUP_RETENTION_DAYS` (por defecto 7 días).

> ⚠️ Por defecto la copia vive en el **mismo host**. Un fallo de disco se lleva
> datos y backup a la vez. Configura la copia off-host (abajo).

## Listar copias disponibles

```
scripts/restore_backup.sh --list
```

## Restaurar

Restaura la copia más reciente (o la de una fecha) al volumen de datos. Para la
app durante la restauración y la vuelve a arrancar:

```
scripts/restore_backup.sh             # última copia de cada BD
scripts/restore_backup.sh 2026-06-28  # copia de esa fecha
```

## Copia off-host (recomendado)

`scripts/backup_offsite.sh` empaqueta el volumen de backup y lo envía a un destino
externo. Pensado para un **cron del host** (las claves SSH/AWS viven en el host):

```
# rsync sobre SSH
DRAWIO_OFFSITE_DEST="user@nas:/vol/backups/drawio" scripts/backup_offsite.sh

# o S3
DRAWIO_OFFSITE_DEST="s3://mi-bucket/drawio" scripts/backup_offsite.sh
```

Ejemplo de cron diario (03:30):

```
30 3 * * * DRAWIO_OFFSITE_DEST="user@nas:/vol/backups/drawio" /home/ubuntu/draw_automatic/scripts/backup_offsite.sh >> /var/log/drawio-offsite.log 2>&1
```

## Prueba de restauración

Conviene probar la restauración periódicamente en un entorno aparte para
confirmar que las copias son válidas (un backup no verificado no es un backup).
