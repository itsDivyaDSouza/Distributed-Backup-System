from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, arp, ipv4


class BackupController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    CLIENT = "10.0.0.1"
    SERVERS = {"10.0.0.2": 3, "10.0.0.3": 4}
    DESTINATIONS = [CLIENT, *SERVERS.keys()]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.down_ports = set()
        self.logger.info("Distributed Backup SDN controller started")

    def path_available(self, primary):
        if primary:
            links = [(1, 2), (2, 1), (2, 2), (4, 1)]
        else:
            links = [(1, 3), (3, 1), (3, 2), (4, 2)]
        return all(link not in self.down_ports for link in links)

    def choose_path(self):
        if self.path_available(True):
            return "primary"
        if self.path_available(False):
            return "backup"
        return None

    def output_port(self, dpid, dst):
        path = self.choose_path()

        if dst in self.SERVERS:
            if dpid == 1:
                return 2 if path == "primary" else 3 if path == "backup" else None
            if dpid == 2:
                return 2 if path == "primary" else None
            if dpid == 3:
                return 2 if path == "backup" else None
            if dpid == 4:
                return self.SERVERS[dst]

        if dst == self.CLIENT:
            if dpid == 1:
                return 1
            if dpid == 2 and path == "primary":
                return 1
            if dpid == 3 and path == "backup":
                return 1
            if dpid == 4:
                return 1 if path == "primary" else 2 if path == "backup" else None

        return None

    def add_flow(self, dp, priority, match, port):
        parser = dp.ofproto_parser
        actions = [parser.OFPActionOutput(port)]
        instructions = [
            parser.OFPInstructionActions(
                dp.ofproto.OFPIT_APPLY_ACTIONS, actions
            )
        ]
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            instructions=instructions
        ))

    def install_table_miss(self, dp):
        parser = dp.ofproto_parser
        self.add_flow(
            dp, 0, parser.OFPMatch(), dp.ofproto.OFPP_CONTROLLER
        )

    def rebuild_flows(self):
        if len(self.datapaths) != 4:
            return

        path = self.choose_path()
        self.logger.info("Rebuilding forwarding rules; selected path=%s", path)

        for dp in self.datapaths.values():
            parser = dp.ofproto_parser
            dp.send_msg(parser.OFPFlowMod(
                datapath=dp,
                command=dp.ofproto.OFPFC_DELETE,
                out_port=dp.ofproto.OFPP_ANY,
                out_group=dp.ofproto.OFPG_ANY,
                match=parser.OFPMatch()
            ))
            self.install_table_miss(dp)

            for dst in self.DESTINATIONS:
                port = self.output_port(dp.id, dst)
                if port is None:
                    continue

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(eth_type=0x0800, ipv4_dst=dst),
                    port
                )
                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(eth_type=0x0806, arp_tpa=dst),
                    port
                )

        self.logger.info("Forwarding rules installed for path=%s", path)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        self.logger.info("Switch connected: s%d", dp.id)
        self.rebuild_flows()

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        port = msg.desc.port_no

        if port >= dp.ofproto.OFPP_MAX:
            return

        key = (dp.id, port)
        down = bool(msg.desc.state & dp.ofproto.OFPPS_LINK_DOWN)

        if down:
            self.down_ports.add(key)
            self.logger.warning("Link down: switch=%d port=%d", dp.id, port)
        else:
            self.down_ports.discard(key)
            self.logger.info("Port available: switch=%d port=%d", dp.id, port)

        self.rebuild_flows()

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None or eth.ethertype == 0x88cc:
            return

        arp_pkt = pkt.get_protocol(arp.arp)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if arp_pkt:
            dst = arp_pkt.dst_ip
        elif ip_pkt:
            dst = ip_pkt.dst
        else:
            return

        port = self.output_port(dp.id, dst)
        if port is None:
            self.logger.warning("No route: switch=%d destination=%s", dp.id, dst)
            return

        actions = [dp.ofproto_parser.OFPActionOutput(port)]
        data = msg.data if msg.buffer_id == dp.ofproto.OFP_NO_BUFFER else None

        dp.send_msg(dp.ofproto_parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=msg.match["in_port"],
            actions=actions,
            data=data
        ))
        self.logger.info(
            "Packet forwarded: switch=%d destination=%s port=%d",
            dp.id, dst, port
        )
