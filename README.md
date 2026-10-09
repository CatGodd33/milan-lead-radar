# Milano Lead Radar

Sistema gratuito que busca nuevos negocios en Milán, los puntúa según su valor comercial, extrae contactos públicos, prepara una frase personalizada, envía alertas por email y publica un panel con mapa.

## Qué hace

- Busca dos veces al día noticias y anuncios recientes mediante Google News RSS.
- Prioriza restaurantes, cafeterías, peluquerías, barberías, centros de belleza, bubble tea y comercios similares.
- Puntúa cada oportunidad de 0 a 100 según fecha, señal de apertura, sector y contacto disponible.
- Intenta obtener email, teléfono, Instagram y dirección desde la fuente pública.
- Geolocaliza direcciones con OpenStreetMap/Nominatim.
- Envía únicamente los prospectos nuevos para evitar emails repetidos.
- Genera una recomendación de servicio y una frase de entrada en italiano/español adaptada al sector.
- Publica un panel responsive con buscador, filtros y mapa mediante GitHub Pages.

## Coste

El funcionamiento normal es gratuito usando los minutos incluidos de GitHub Actions, GitHub Pages, Gmail y OpenStreetMap. No utiliza APIs de IA ni servicios de pago.

## Activación en GitHub

1. Crea un repositorio público o privado y sube estos archivos.
2. En **Settings → Secrets and variables → Actions**, crea:
   - `GMAIL_USER`: cuenta Gmail que enviará los avisos.
   - `GMAIL_APP_PASSWORD`: contraseña de aplicación de Google de 16 caracteres. No uses la contraseña normal.
   - `ALERT_TO`: dirección en la que quieres recibir los avisos.
3. Para obtenerla, activa la verificación en dos pasos de Google y crea una contraseña de aplicación.
4. En **Settings → Pages → Source**, selecciona **GitHub Actions**.
5. Abre **Actions → Buscar nuevos negocios → Run workflow** para hacer la primera búsqueda.

La dirección receptora se guarda únicamente como secreto `ALERT_TO`; no aparece en el repositorio público.

## Ejecución local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/radar.py --no-email
```

Para probar el email, copia `.env.example` a `.env`, exporta las variables en tu terminal y ejecuta sin `--no-email`. El programa nunca guarda las credenciales.

## Personalización

Edita `config.json` para cambiar:

- búsquedas y sectores;
- antigüedad máxima;
- puntuación mínima;
- máximo de resultados por búsqueda;
- cantidad máxima de negocios por email.

## Limitaciones honestas

- Ninguna fuente pública contiene todas las aperturas. El sistema descubre señales publicadas en medios y páginas indexadas.
- Instagram, Facebook y Google Maps restringen la extracción automatizada; el radar conserva enlaces públicos encontrados, pero no intenta evadir esas restricciones.
- Algunos artículos no muestran teléfono o dirección. Esos prospectos siguen apareciendo, señalados para investigación o visita presencial.
- Antes de realizar campañas masivas, respeta RGPD y normas anti-spam. El email automático del sistema se envía solo al propietario del radar, no a los negocios.
