# =====================================================================
# La imagen de la demo publica. Solo la aplicacion: la base es un
# servicio aparte y gestionado.
#
# POR QUE `slim` Y NO `alpine`
#   requirements.txt fija que todo se instale desde rueda precompilada
#   (DR-6): sin cadena de compilacion. Alpine usa musl y para varias de
#   estas dependencias no hay rueda, asi que obligaria a compilar —justo
#   lo que esa decision evita—.
#
# POR QUE LA VERSION VA FIJADA
#   3.13 es la de la maquina de desarrollo y la del CI. Dejarla flotante
#   haria que la demo publica corriera un interprete distinto del que se
#   mide, y entonces "esto es lo que esta medido" dejaria de ser cierto.
# =====================================================================
FROM python:3.13-slim

WORKDIR /app

# Las dependencias primero y en su propia capa: cambian mucho menos que
# el codigo, asi que se reaprovechan entre despliegues.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sin buffer: si Python acumula la salida, la bitacora aparece en el
# visor de logs a rachas y con retraso. Y la bitacora ES el registro en
# el despliegue, porque el disco de aqui es efimero.
ENV PYTHONUNBUFFERED=1

# El servicio corre detras del balanceador de la plataforma, asi que la
# direccion del socket es la suya. Sin esto, el limite de tasa contaria
# TODO el trafico como una sola IP y bloquearia a todo el mundo a la vez.
ENV HAY_PROXY=1

# Un usuario sin privilegios. No protege de nada que el guardian no
# cubra ya, pero un proceso de red corriendo como root es una decision
# que nadie tomo, y esas son las que salen caras.
RUN useradd --create-home --uid 10001 demo && chown -R demo:demo /app
USER demo

# El esquema se aplica al arrancar si la base esta vacia, y si eso falla
# el contenedor NO arranca. Un servicio en pie con las revocaciones a
# medias seria el peor desenlace: todo parece funcionar.
CMD ["sh", "-c", "python despliegue/preparar.py && python app/servidor.py"]
