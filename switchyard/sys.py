import sys
import heapq
from collections import namedtuple
import threading
from queue import Queue,Empty
import time
from importlib import import_module
from cmd import Cmd
import re
from abc import ABCMeta,abstractmethod


from switchyard.switchyard.switchy import LLNetBase
from switchyard.switchyard.switchy_common import NoPackets,Shutdown
from switchyard.monitor import *
from switchyard.lib.topo import *
from switchyard.lib.packet import *
from switchyard.lib.textcolor import *
from switchyard.lib.importcode import import_user_code


__author__ = 'jsommers@colgate.edu'
__doc__ = 'SwitchYard Substrate Simulator'

EgressPipe = namedtuple('EgressPipe', ['queue','delay','capacity','remote_devname'])


class LinkEmulator(object):
    def __init__(self, inqueue):
        self.expiryheap = []
        self.inqueue = inqueue
        self.__shutdown = False

    def shutdown(self):
        self.__shutdown = True

    def run(self):
        while not self.__shutdown:

            now = time.time()
            while len(self.expiryheap) and self.expiryheap[0][0] <= now:
                expiretime,item,outqueue = heapq.heappop(self.expiryheap)
                outqueue.put(item)

            if len(self.expiryheap):
                expiretime,item,outqueue = self.expiryheap[0]
                timeout = expiretime - time.time()
            else:
                timeout = 1.0

            try:
                expiretime,item,outqueue = self.inqueue.get(timeout=timeout)
            except Empty:
                pass
            else:
                heapq.heappush(self.expiryheap, (expiretime, item, outqueue))

class NodeExecutor(LLNetBase):
    __slots__ = ['__done', '__ingress_queue', '__egress_pipes', '__name','__interfaces','__symod', '__linkem', '__tolinkem','__recv_monitor']
    def __init__(self, name, ingress_queue, symod=None):
        LLNetBase.__init__(self)
        self.__ingress_queue = ingress_queue
        self.__egress_pipes = {}
        self.__name = name
        self.__interfaces = {}
        self.__symod = symod
        self.__done = False
        self.__linkem = None
        self.__tolinkem = None
        self.__recv_monitor = {'host': NullMonitor()}

    def sendHostPacket(self, pkt):
        self.__ingress_queue.put( ('host', pkt) )

    def addEgressInterface(self, devname, intf, queue, capacity, delay, remote_devname):
        print ("Adding egress interface on {} {}".format(self.name, devname))
        self.__egress_pipes[devname] = EgressPipe(queue, delay, capacity, remote_devname)
        self.__interfaces[devname] = intf
        self.__recv_monitor[devname] = NullMonitor()

    @property
    def name(self):
        return self.__name

    def interfaces(self):
        return self.__interfaces.values()

    def set_devupdown_callback(self, callback):
        pass

    def interface_by_name(self, name):
        return self.__interfaces[name]

    def interface_by_ipaddr(self, ipaddr):
        pass

    def interface_by_macaddr(self, macaddr):
        pass

    def attach_recv_monitor(self, interface, monitorobject):
        self.__recv_monitor[interface] = monitorobject

    def remove_recv_monitor(self, interface):
        self.__recv_monitor[interface] = NullMonitor()

    def recv_packet(self, timeout=0.0, timestamp=False):
        #
        # FIXME: not sure about how best to handle...
        #
        giveup_time = time.time() + timeout
        inner_timeout = 0.1
         
        while timeout == 0.0 or time.time() < giveup_time:
            try:
                devname,packet = self.__ingress_queue.get(block=True, timeout=inner_timeout)
                now = time.time()
                self.__recv_monitor[devname](devname,now,packet)
                if timestamp:
                    return devname,now,packet
                return devname,packet
            except Empty:
                pass

            if self.__done:
                raise Shutdown()

        raise NoPackets()

    def send_packet(self, dev, packet):
        egress_pipe = self.__egress_pipes[dev]
        now = time.time()
        delay = now + len(packet) / float(egress_pipe.capacity) + egress_pipe.delay
        self.__tolinkem.put( (delay, (egress_pipe.remote_devname, packet), egress_pipe.queue) )

    def shutdown(self):
        self.__linkem.shutdown()
        self.__done = True

    def __idleloop(self):
        while not self.__done:
            try:
                devname,ts,packet = self.recv_packet(timestamp=True)
            except Shutdown:
                break
            except NoPackets:
                pass

    def run(self):
        self.__tolinkem = Queue()
        self.__linkem = LinkEmulator(self.__tolinkem)
        t = threading.Thread(target=self.__linkem.run)
        t.start()
        self.startcode()

    def resetcode(self, mod=None):
        self.__symod = mod
        self.startcode()

    def startcode(self):
        if self.__symod:
            print ("Starting code {}".format(self.name))
            self.__symod(self)
        else:
            self.__idleloop()

NodePlumbing = namedtuple('NodePlumbing', ['thread','nexec','queue'])

class Cli(Cmd):
    def __init__(self, syss_glue, topology):
        self.syss_glue = syss_glue
        # self.nodedata = syss_glue.xnode
        self.topology = topology
        Cmd.__init__(self)
        self.unsaved_changes = False
        self.prompt = '{}switchyard>{} '.format(TextColor.CYAN,TextColor.RESET)
        self.use_rawinput = True
        self.doc_header = '''
FIXME: this is the documentation header.
'''

        try:
            import readline
        except ImportError:
            pass
        else:
            readline.clear_history()

    def do_show(self, line):
        cmdargs = line.split()
        if len(cmdargs) < 1:
            print ("Not enough arguments to show ('help show' for more info)")
            return

        if 'links'.startswith(cmdargs[0]):
            self.__show_links(cmdargs[1:])
        elif 'nodes'.startswith(cmdargs[0]):
            self.__show_nodes(cmdargs[1:])
        elif 'topology'.startswith(cmdargs[0]):
            self.__show_topology(cmdargs[1:])
        elif 'monitor'.startswith(cmdargs[0]):
            print ("show monitor not implemented")
        elif '?' == cmdargs[0]:
            self.help_show() 
        else:
            print ("Invalid show subcommand {}".format(cmdargs[0]))

    def complete_show(self, text, line, begidx, endidx):
        # print ("text: {} line: {} begidx: {} endidx: {}".format(text,line,begidx,endidx))
        #if 'nod'.startswith(text):
        #    return ['node','nodes']
        #elif 'show node'.startswith(line):
        #    return [ "node {}".format(n) for n in self.topology.nodes ]
        #elif 'show link'.startswith(line):
        #    return [ "link {}".format(n) for n in self.topology.nodes ]
        #elif 'lin'.startswith(text):
        #    return ['link','links']
        #elif 'topology'.startswith(text):
        #    return ['topology']
        return []

    def do_set(self, line):
        argerr = "Not enough arguments to set ('help set' for more info)"
        cmdargs = line.split()
        if len(cmdargs) < 5:
            print (argerr)
            return

        if 'node'.startswith(cmdargs[0]):
            nodename = cmdargs[1]
            interface = cmdargs[2]
            ethaddr = None
            ipaddr = None
            netmask = None
            if 'ethernet'.startswith(cmdargs[3]):
                ethaddr = cmdargs[4]
            elif 'inet'.startswith(cmdargs[3]):
                ipaddr = cmdargs[4]
                netmask = ''
                if len(cmdargs) > 5:
                    if 'netmask'.startswith(cmdargs[5]):
                        if len(cmdargs) > 6:
                            netmask = cmdargs[6]
                        else:
                            print ("Missing netmask value")
                            return
                    elif len(cmdargs) == 6:
                        netmask = cmdargs[5]
                    else:
                        print ("Unrecognized configuration parameter")
                        return
                try:
                    self.topology.setInterfaceAddresses(nodename, interface, mac=ethaddr, ip=ipaddr, netmask=netmask)
                except Exception as e:
                    print ("Error setting addresses: {}".format(str(e)))
            else:
                print ("Invalid address family: must be ethernet or inet")
                return

        elif 'link'.startswith(cmdargs[0]):
            n1,n2 = cmdargs[1:3]
            cmdargs = cmdargs[3:]
            settings = self.__gather_link_characteristics(cmdargs)

            try:
                self.topology.setLinkCharacteristics(n1, n2, capacity=settings['capacity'], delay=settings['delay'])
            except Exception as e:
                print ("Error setting link characteristics: {}".format(str(e)))
        else:
            print ("Invalid set command: must start with 'set node' or 'set link'")

    def __gather_link_characteristics(self, cmdargs):
        settings = {'capacity': None, 'delay':None}
        currsetting = ''
        currval = []
        while len(cmdargs):
            cmdval = cmdargs.pop(0)
            if cmdval == 'bw' or 'bandwidth'.startswith(cmdval) or 'capacity'.startswith(cmdval):
                if currsetting:
                    settings[currsetting] = ' '.join(currval)
                currval = []
                currsetting = 'capacity'
            elif 'delay'.startswith(cmdval):
                if currsetting:
                    settings[currsetting] = ' '.join(currval)
                currval = []
                currsetting = 'delay'
            else:
                currval.append(cmdval)
        if currsetting:
            settings[currsetting] = ' '.join(currval)
        return settings

    def do_save(self, line):
        cmdargs = line.split()
        if len(cmdargs) != 1:
            print ("Invalid number of arguments.  Only the filename to save topology as should be given.")
            return
        save_to_file(self.topology, cmdargs[0])
        print ("Topology saved to {}".format(cmdargs[0]))
        self.unsaved_changes = False

    def do_load(self, line):
        cmdargs = line.split()
        if len(cmdargs) != 1:
            print ("Invalid number of arguments.  The filename from which to load the topology is the only required argument.")
            return

        if self.unsaved_changes:
            prompt = "You have unsaved changes to the topology.  Loading a new topology will destroy those changes.  Are you sure you want to continue? (y/n)"
            xcontinue = self.__get_yn(prompt)
            if not xcontinue:
                return

        try:
            self.topology = load_from_file(cmdargs[0])
        except FileNotFoundError:
            print ("No file {} exists.".format(cmdargs[0]))
            return

        self.unsaved_changes = False
        self.syss_glue.stop()
        self.syss_glue.rebuildGlue(self.topology) # FIXME: exec code?

    def emptyline(self):
        pass

    def do_remove(self, line):
        cmdargs = line.split()
        if len(cmdargs) < 2:
            print ("Invalid number of arguments to 'remove'")
            return

        cmdval = cmdargs.pop(0)
        if 'node'.startswith(cmdval) or 'switch'.startswith(cmdval) or 'router'.startswith(cmdval) or 'host'.startswith(cmdval):
            if len(cmdargs) != 1:
                print ("Invalid number of arguments: just need the node name")
                return
            try:
                self.topology.removeNode(cmdargs[0])
            except Exception as e:
                print ("Error removing node: {}".format(str(e)))

        elif 'edge'.startswith(cmdval) or 'link'.startswith(cmdval):
            if len(cmdargs) != 2:
                print ("Invalid number of arguments: need two node names to define a link to remove")
                return
            try:
                self.topology.removeLink(*cmdargs)
            except Exception as e:
                print ("Error removing link: {}".format(str(e)))

        else:
            print ("Unrecognized argument {} to remove.".format(cmdval))
            return

        self.unsaved_changes = True
        self.syss_glue.rebuildGlue(self.topology) # FIXME: exec code?

    def do_add(self, line):
        cmdargs = line.split()
        if len(cmdargs) < 1:
            print ("Not enough arguments to 'add'")
            return
        cmdval = cmdargs.pop(0)
        name = None
        if 'switch'.startswith(cmdval):
            if cmdargs:
                name = cmdargs[0]
            n = self.topology.addSwitch(name)
            print ("Added switch {}".format(n))
        elif 'router'.startswith(cmdval):
            if cmdargs:
                name = cmdargs[0]
            n = self.topology.addRouter(name)
            print ("Added router {}".format(n))
        elif 'host'.startswith(cmdval):
            if cmdargs:
                name = cmdargs[0]
            n = self.topology.addHost(name)
            print ("Added host {}".format(n))
        elif 'link'.startswith(cmdval):
            if len(cmdargs) < 6:
                print ("Invalid number of arguments to 'set link': need two nodes as well as bandwidth and capacity (see 'help add')")
                return
            n1,n2 = cmdargs[:2]
            cmdargs = cmdargs[2:]
            settings = self.__gather_link_characteristics(cmdargs)
            try:
                self.topology.addLink(n1, n2, capacity=settings['capacity'], delay=settings['delay'])
                n1node = self.topology.getNode(n1)['nodeobj']
                print("Added link {}<->{} ({})".format(n1, n2, self.topology.getLink(n1,n2)['label']))
            except Exception as e:
                print ("Error add link: {}".format(str(e)))
        else:
            print ("Unrecognized argument: '{}'".format(cmdval))
            return
        self.unsaved_changes = True
        self.syss_glue.rebuildGlue(self.topology) # FIXME: exec code?

    def __exec_monitor(self, cmdargs, monitorfn, unmonitor=False):
        if len(cmdargs) < 1:
            print("Not enough arguments to monitor command")
            return
        location = []
        where = cmdargs.pop(0)
        if 'any'.startswith(where) or 'all'.startswith(where):
            for n in self.topology.nodes:
                nobj = self.topology.getNode(n)['nodeobj']
                for intf in nobj.interfaces.keys():
                    location.append( (n,intf) )
        elif 'node'.startswith(where):
            if len(cmdargs) < 1:
                print("Not enough arguments to monitor node")
                return
            where = cmdargs.pop(0)
            if self.topology.hasNode(where):
                location = [ where ]
                nobj = self.topology.getNode(where)['nodeobj']
                if len(cmdargs) > 0 and cmdargs[0].startswith('eth'):
                    interface = cmdargs.pop(0)
                    if not nobj.hasInterface(interface):
                        print ("No such interface {} on node {}".format(interface,where))
                        return
                    location = [ (where,interface) ]
                else:
                    location = [ (where,intf) for intf in nobj.interfaces.keys() ]
        else:
            print ("Unrecognized monitor location.  Must be 'any' or 'node <nodename>'.")
            return
        if unmonitor:
            return location

        how = []
        if not len(cmdargs):
            print ("Not enough arguments to monitor command.  Need to know whether to dump, debug, or install monitor code")
            return
        cmdval = cmdargs.pop(0)
        if 'dump'.startswith(cmdval) or 'pcap'.startswith(cmdval) or 'file'.startswith(cmdval):
            if cmdargs:
                filebase = cmdargs.pop(0)
            else:
                filebase = 'FIXME'
            how = ( 'pcap',  filebase)
        elif 'debug'.startswith(cmdval) or 'inspect'.startswith(cmdval) or 'trace'.startswith(cmdval):
            how = ( 'debug', )
        elif 'code'.startswith(cmdval) or 'install'.startswith(cmdval):
            if not cmdargs:
                print ("Missing file name for monitor code")
                return
            how = ( 'code', cmdargs[0] )

        for node, intf in location:
            monitorfn(node, intf, how[0], *how[1:])

    def do_unmonitor(self, line):
        cmdargs = line.split()
        self.__exec_monitor(cmdargs, self.syss_glue.removeMonitor, unmonitor=True)

    def do_monitor(self, line):
        cmdargs = line.split()
        self.__exec_monitor(cmdargs, self.syss_glue.addMonitor)

    def __show_nodes(self, cmdargs):
        if len(cmdargs) == 0:
            print (' '.join(self.topology.nodes))
        else:
            if cmdargs[0] in self.topology.nodes:
                nobj = self.topology.getNode(cmdargs[0])
                nodeifs = nobj['nodeobj'].interfaces
                plural = 's'
                if len(nodeifs) == 1: plural = ''
                print ("Node {} is a {} and has {} interface{}:".format(cmdargs[0], nobj['type'], len(nodeifs), plural))
                for ifname,intf in sorted(nodeifs.items()):
                    print ("\t{}".format(intf))
            else:
                print ("Node {} does not exist.".format(cmdargs[0]))

    def __printlink(self, u, v, ldict):
        print ('{} <-> {} ({})'.format(u,v,ldict['label']))

    def __show_links(self, cmdargs):
        if len(cmdargs) == 0:
            # show all links
            for u,v in self.topology.links:
                linkdict = self.topology.getLink(u,v)
                self.__printlink(u,v,linkdict)
        else:
            if cmdargs[0] in self.topology.nodes: 
                # show links related to a given node
                for u,v in self.topology.edges_from(cmdargs[0]):
                    linkdict = self.topology.getLink(u,v)
                    self.__printlink(u,v,linkdict)
            else:
                print ("Can't show links for unknown node {}".format(cmdargs[0]))

    def __show_topology(self, cmdargs):
        print ("Close window in order to proceed")
        showaddrs = showintfs = False
        for arg in cmdargs:
            if arg.startswith('addr'):
                showaddrs = True
                showintfs = True
            elif arg.startswith('int'):
                showintfs = True
        show_graph(self.topology, showaddrs=showaddrs, showintfs=showintfs)

    def do_sendeth(self, line):
        sourcenode = line.strip()
        if not self.topology.hasNode(sourcenode):
            print ("Invalid node name: '{}'".format(sourcenode))
        else:
            p = Packet()
            e = Ethernet()
            e.src = '00:00:00:00:00:01'
            e.dst = '11:00:00:11:00:11'
            print ("Emitting {} from host {}".format(e, sourcenode))
            p += e
            self.syss_glue.sendHostPacket(sourcenode, e)

    def do_EOF(self, line):
        return self.do_exit(line)

    @staticmethod
    def __get_yn(prompt):
        while True:
            value = input(prompt)
            if 'no'.startswith(value.lower()):
                return False
            elif 'yes'.startswith(value.lower()):
                return True

    def do_exit(self, line):
        if self.unsaved_changes:
            prompt = "You have unsaved topology changes.  Are you sure you want to exit? (y/n)"
            xcontinue = self.__get_yn(prompt)
            if not xcontinue:
                print ("Not exiting.")                 
                return

        self.syss_glue.stop()
        return True

    def default(self, line):
        '''
        Implement short-cut commands: any unique command prefix should
        work.'''
        cmdargs = line.split()
        if re.match('^sh', cmdargs[0]):
            self.do_show(' '.join(cmdargs[1:]))
        elif re.match('^set', cmdargs[0]):
            self.do_sendeth(' '.join(cmdargs[1:]))
        elif re.match('^set', cmdargs[0]):
            self.do_set(' '.join(cmdargs[1:]))
        else:
            print ("Unrecognized command '{}'".format(line))

    def help_monitor(self):
        print ('''
            FIXME: help on monitor command
        ''')

    def help_add(self):
        print ('''
        add host [<hostname>]
        add switch [<switchname>]
        add router [<routername>]
        add link <node1> <node2> capacity <capacity> delay <delay>
        ''')

    def help_show(self):
        print ('''
        show (nodes|node <nodename>)
        show (links|link <nodename>)
        show topology 
        ''')

    def help_set(self):
        print ('''
        set node <nodename> <ifacename> ethernet <ethaddr>
        set node <nodename> <ifacename> inet <ipaddr> [netmask <mask>]
        set node <nodename> <ifacename> inet <ipaddr>/<prefixlen>
        set link <node1> <node2> [capacity <capacity>] [delay <delay>]
        ''')

    def help_exit(self):
        print ("Really?  You need help for the exit command?")

    def help_EOF(self):
        self.help_exit()

    def help_sendeth(self):
        print ("Flood a simple raw Ethernet packet from a node")

class SyssGlue(object):
    def __init__(self, topo, **kwargs):
        self.monitors = {}
        self.monitors['pcap'] = PcapMonitor
        self.monitors['debug'] = InteractiveMonitor
        self.monitors['code'] = CodeMonitor

        self.rebuildGlue(topo, **kwargs)

    def sendHostPacket(self, node, pkt):
        self.xnode[node].nexec.sendHostPacket(pkt)

    def rebuildGlue(self, topo, **kwargs):
        print ("In rebuild glue with nodeexec: {}".format(kwargs.get('nodeexec','?')))
        try:
            self.shutdown()
        except:
            pass

        self.xnode = {}
        execmodule = None
        if 'nodeexec' in kwargs:
            execmodule = import_user_code(kwargs['nodeexec'])
        else:
            if 'switchcode' in kwargs:
                pass
            if 'routercode' in kwargs:
                pass
            if 'hostcode' in kwargs:
                pass

        # exec_module = import_module(swycode)
        self.ingress_queues = {}

        for n in topo.nodes:
            self.__addNode(n, execmodule)

        for u,v in topo.links:
            linkdict = topo.getLink(u,v)
            unode = topo.getNode(u)['nodeobj']
            self.__addLink(u, v, unode, linkdict)

        self.__start()

    def __addNode(self, n, execmodule=None):
        print ("Adding node with execmod: {}".format(execmodule))
        self.ingress_queues[n] = q = Queue()
        nexec = NodeExecutor(n, q, execmodule)
        t = threading.Thread(target=nexec.run)
        self.xnode[n] = NodePlumbing(t,nexec,q)

    def __addLink(self, u, v, unode, linkdict):
        nearnode = self.xnode[u]
        farnode = self.xnode[v]
        udev = linkdict[u]
        vdev = linkdict[v]
        cap = linkdict['capacity']
        delay = linkdict['delay']
        egress_queue = farnode.queue
        intf = unode.getInterface(udev)
        nearnode.nexec.addEgressInterface(udev, intf, egress_queue, cap, delay, vdev)

    def __start(self):
        for nodename,plumbing in self.xnode.items():
            plumbing.thread.start()

    def stop(self):
        for np in self.xnode.values():
            np.nexec.shutdown()
            np.thread.join()
            del np

    def addMonitor(self, node, interface, how, *args, **kwargs):
        print ("Add monitor {} {} {} {}".format(node, interface, how, args))
        self.xnode[node].nexec.attach_recv_monitor(interface, self.monitors[how](*args))

    def removeMonitor(self, node, interface, how, *args):
        print ("Remove monitor {} {} {} {}".format(node, interface, how, args))
        self.xnode[node].nexec.remove_recv_monitor(interface)

def run_simulation(topo, **kwargs):
    '''
    Get the simulation substrate started.  The key things are to set up
    a series of queues that connect nodes together and get the link emulation
    objects started (all inside the NodeExecutor class).  The NodePlumbing
    named tuples hold together threads for each node, the emulation
    substrate (NodeExecutors), and the ingress queue that each node receives
    packets from.
    '''
    print ("In run simulation with nodeexec: {}".format(kwargs.get('nodeexec','?')))
    glue = SyssGlue(topo, **kwargs)
    cli = Cli(glue, topo)
    cli.cmdloop()


def main():
    topofile = None
    swycode = None
    if len(sys.argv) > 1:
        topofile = sys.argv[1]
    if len(sys.argv) > 2:
        swycode = sys.argv[2]
    if not (topofile and swycode):
        print ("Need topofile and swy code")
        sys.exit(-1)

    topo = load_from_file(topofile)
    run_simulation(topo, swycode)

if __name__ == '__main__':
    main()