# Inside the container gunicorn must listen on all interfaces or Docker
# cannot reach it. The loopback restriction is applied on the host side,
# in the compose port mapping.
bind = "0.0.0.0:8002"

# Two workers is right for a Pi with a handful of concurrent field
# users. The usual 2*cores+1 rule would give 9 on a Pi 4 and spend
# most of the available RAM on idle Django processes.
workers = 2

# The default 30s is marginal for a photo upload over rural 4G.
timeout = 120
graceful_timeout = 30
keepalive = 5

# Requests arrive via the Cloudflare tunnel, so the forwarded headers
# must be trusted for Django to see the correct scheme and host.
forwarded_allow_ips = "*"

accesslog = "-"
errorlog = "-"
loglevel = "info"
