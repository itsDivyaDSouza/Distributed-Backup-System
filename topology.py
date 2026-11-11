#!/usr/bin/env python3

from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info


def create_topology():
    net = Mininet(
        controller=None,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True
    )

    net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6653
    )

    info("*** Adding hosts\n")
    h1 = net.addHost("h1", ip="10.0.0.1/24")
    h2 = net.addHost("h2", ip="10.0.0.2/24")
    h3 = net.addHost("h3", ip="10.0.0.3/24")

    info("*** Adding switches\n")
    s1 = net.addSwitch(
        "s1", dpid="0000000000000001", protocols="OpenFlow13"
    )
    s2 = net.addSwitch(
        "s2", dpid="0000000000000002", protocols="OpenFlow13"
    )
    s3 = net.addSwitch(
        "s3", dpid="0000000000000003", protocols="OpenFlow13"
    )
    s4 = net.addSwitch(
        "s4", dpid="0000000000000004", protocols="OpenFlow13"
    )

    info("*** Adding client connection\n")
    net.addLink(h1, s1)

    info("*** Adding primary path: s1-s2-s4\n")
    net.addLink(s1, s2, cls=TCLink, bw=20, delay="5ms")
    net.addLink(s2, s4, cls=TCLink, bw=20, delay="5ms")

    info("*** Adding backup path: s1-s3-s4\n")
    net.addLink(s1, s3, cls=TCLink, bw=10, delay="10ms")
    net.addLink(s3, s4, cls=TCLink, bw=10, delay="10ms")

    info("*** Connecting backup servers\n")
    net.addLink(s4, h2)
    net.addLink(s4, h3)

    info("*** Starting network\n")
    net.start()

    info("*** Network ready. Try: net, pingall, links\n")
    CLI(net)
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    create_topology()