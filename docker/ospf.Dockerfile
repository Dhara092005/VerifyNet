FROM quay.io/frrouting/frr:10.4.5

# The upstream runtime image is intentionally minimal and ships ospfd=no.
# Add Alpine's FRR package so the disposable research lab has OSPF daemons.
RUN apk add --no-cache frr
RUN sed -i 's/^ospfd=no/ospfd=yes/' /etc/frr/daemons
