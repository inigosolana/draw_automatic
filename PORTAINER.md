# Despliegue en Portainer

## Preparacion del servidor

1. Crea el directorio persistente:

```bash
sudo mkdir -p /opt/ausarta-drawio
sudo cp libreria_Ausarta_JUN_2026.xml /opt/ausarta-drawio/
sudo chmod 644 /opt/ausarta-drawio/libreria_Ausarta_JUN_2026.xml
```

2. Renueva los tokens GLPI y utiliza una cuenta tecnica con permisos minimos.

## Stack desde GitHub

1. En Portainer abre `Stacks` y selecciona `Add stack`.
2. Elige `Repository`.
3. Indica el repositorio y la rama `main`.
4. Usa `docker-compose.yml` como ruta del fichero Compose.
5. Configura las variables de `.env.example` en `Environment variables`.
   Genera `DRAWIO_SECRET_KEY` con una cadena aleatoria de al menos 32 bytes.
6. Despliega el stack.

## Comprobaciones

- Aplicacion: `http://IP_SERVIDOR:8000`
- Salud: `http://IP_SERVIDOR:8000/health`
- Consulta de diagramas: `http://IP_SERVIDOR:8000/diagrams`
- Login: utiliza las mismas credenciales personales que GLPI.

La previsualizacion usa el visor embebido de diagrams.net. Si los diagramas contienen
datos sensibles, despliega una instancia privada de draw.io y sustituye
`DRAWIO_PREVIEW_URL` por su URL antes de exponer la aplicacion.

## Publicacion HTTPS

No expongas directamente el puerto 8000 a Internet. Publicalo mediante Nginx Proxy
Manager, Traefik o el proxy corporativo con:

- certificado TLS;
- limite de peticiones;
- autenticacion corporativa o SSO;
- cabeceras `X-Forwarded-For` y `X-Forwarded-Proto`.

## Copias de seguridad

Haz copia diaria del volumen `drawio_data`. Los diagramas definitivos permanecen en
GLPI, pero el volumen contiene borradores pendientes y la base de conocimiento local.
Tambien contiene `sites.sqlite3`, donde se conservan las direcciones exactas corregidas
por los tecnicos para cada ID de sede GLPI.

## Integracion futura con CRM

La aplicacion ya permite trabajar aunque GLPI tenga la direccion incompleta. Cuando el
CRM disponga de API, se puede consultar la direccion por cliente/sede y actualizar
automaticamente `sites.sqlite3`, manteniendo GLPI como identificador principal.
