#!/usr/bin/python
# This is the main configuration file for setting up SOS.
# It will be responsible for doing a few things:
#       - Deleting firewall rules
#       - Deleting any queueing system
#       - Configuring all the network parameters
#       - Pinning all of the interrupts
#       - Installing and configuring OVS
#       - Installing and configure the SOS agent

import fileinput
import multiprocessing
import os
import re
import subprocess
import sys


# Get the package manager.. yum for CentOS and apt-get for Ubuntu
def getPackageManager():
    r = subprocess.call("cat /etc/*-release | grep -c CentOS", shell=True)
    if r == 0:
        print("CentOS detected. Using yum as package manager..")
        return "yum"
    else:
        print("Using apt-get as package manager..")
        return "apt-get"


def deleteFirewallRules():
    print("\nDELETING FIREWALL RULES")

    print("Flushing iptables rules.")
    subprocess.call("sudo iptables --flush", shell=True)

    print("Saving flushed iptables to file. Changes will be saved if service is restarted.")
    subprocess.call("sudo service iptables save", shell=True)


def deleteQueueingSystems():
    ##We might have to extend this to iterate for every interface
    while True:
        print("\nInterface:")
        subprocess.call("ip addr | grep mtu | awk '/mtu/{print $2,$6,$7}'", shell=True)
        print("\n")
        interface = raw_input("Which interface to delete the queues?? >> ")
        try:
            print "\nDeleting queues for interface", interface
            subprocess.check_call("sudo tc -s qdisc ls dev " + interface, shell=True)
            subprocess.check_call("sudo tc qdisc replace dev " + interface + " root pfifo limit 10000", shell=True)
            print "Queues deleted for interface", interface
            choice = raw_input("Queues deleted! Do you want to delete another? >> ")
        except subprocess.CalledProcessError:
            print "No queues found for interface", interface
            choice = raw_input("Try again? >> ")

        choice = choice.strip().lower()
        if choice == "no" or choice == "n":
            break


def configureNetworkParameters():
    print("\nCONFIGURING TCP PARAMETERS")

    print("Setting parameters in /proc/sys/net/..")
    # recommended default congestion control is htcp
    subprocess.call("echo 'htcp' > /proc/sys/net/ipv4/tcp_congestion_control", shell=True)

    # if set to 1, prefer lower latency as opposed to higher throughput
    subprocess.call("echo 1 > /proc/sys/net/ipv4/tcp_low_latency", shell=True)

    # These are the most important settings, especially if you're using Gigabit networking
    # there shouldn't be any penalty to applying them to every server

    # The hard limits for the maximum amount of socket buffer space, in bytes.
    subprocess.call("echo 134217728 > /proc/sys/net/core/rmem_max", shell=True)
    subprocess.call("echo 134217728 > /proc/sys/net/core/wmem_max", shell=True)

    # These are the corresponding settings for the IP protocol, in the format (min, default, max) bytes.
    # The max value can't be larger than the equivalent net.core.{r,w}mem_max.
    subprocess.call("echo '4096 87380 67108864' > /proc/sys/net/ipv4/tcp_rmem", shell=True)
    subprocess.call("echo '4096 87380 67108864' > /proc/sys/net/ipv4/tcp_wmem", shell=True)

    # Don't touch tcp_mem for two reasons: Firstly, unlike tcp_rmem and tcp_wmem it's in pages, not bytes, so it's
    # likely to confuse the hell out of you. Secondly, it's already auto-tuned very well by Linux based on the
    # amount of RAM.
    # subprocess.call("echo '16777216 16777216 16777216' > /proc/sys/net/ipv4/tcp_mem", shell=True)

    # Increase the number of outstanding syn requests allowed.
    subprocess.call("echo 4096 > /proc/sys/net/ipv4/tcp_max_syn_backlog", shell=True)

    subprocess.call("echo 300000 > /proc/sys/net/core/netdev_max_backlog", shell=True)

    # # turn off selective ACK and timestamps
    # subprocess.call("echo 0 > /proc/sys/net/ipv4/tcp_sack", shell=True)
    # subprocess.call("echo 0 > /proc/sys/net/ipv4/tcp_timestamps", shell=True)
    #
    # print("Setting parameters in /proc/sys/net/core/..")
    # subprocess.call("echo 16777216 > /proc/sys/net/core/optmem_max", shell=True)
    # subprocess.call("echo 16777216 > /proc/sys/net/core/rmem_default", shell=True)
    # subprocess.call("echo 16777216 > /proc/sys/net/core/wmem_default", shell=True)


def pinInterrupts():
    print("PINNING INTERRUPTS")

    print("Stopping the irqbalance service..")
    subprocess.call("sudo service irqbalance stop", shell=True)
    subprocess.call("sudo service irqbalance status", shell=True)

    # TODO: Make it more obvious which is the right interface to choose. Clean up UI.
    while True:
        print("\nInterface:")
        subprocess.call("ifconfig | sed 's/[ \t].*//;/^\(lo\|\)$/d'", shell=True)
        print("\n")
        interface = raw_input("What interface do you want to pin? >> ")
        subprocess.call("ifconfig " + interface, shell=True)
        confirm = raw_input("Are you sure you want to pin interrupts for interface " + interface + "? >> ")
        confirm = confirm.strip().lower()
        if confirm == "yes" or confirm == "y":
            ipoutput = subprocess.check_output("ip link", shell=True)
            matching = [s for s in ipoutput.split('\n') if interface in s]
            for match in matching:
                links = match.split(' ')[1].split('@')
                if len(links) == 1:
                    interface = links[0].split(':')[0]
                    print "Using physical interface: " + interface
                    break
                elif len(links) == 2:
                    interface = links[1].split(':')[0]
                    print "Using physical interface: " + interface
            break

    # TODO: Make sure this works for every version of python.
    if sys.version_info[:2] == (2, 6):
        print("Python v2.6 detected. Using Popen.")
        interrupt_output = subprocess.Popen("cat /proc/interrupts | grep " + interface, shell=True,
                                            stdout=subprocess.PIPE)
        interrupt_output = interrupt_output.communicate()[0]
        all_output = subprocess.Popen("cat /proc/interrupts", shell=True,
                                      stdout=subprocess.PIPE)
        all_output = all_output.communicate()[0]

    else:
        print("Python version greater than v2.6 detected. Using check_output.")
        interrupt_output = subprocess.check_output("cat /proc/interrupts | grep " + interface, shell=True)
        all_output = subprocess.check_output("cat /proc/interrupts", shell=True)

    interrupt_output = interrupt_output.split('\n')

    all_output = all_output.split('\n')
    all_output.pop(0)

    num_cpus = multiprocessing.cpu_count()
    print("\nYou have " + str(num_cpus) + " cpus!\n")

    # Move everything over to core 0
    if num_cpus > 1:
        print("\nPushing every interrupt over to core 0.\n")
        for index, interrupt in enumerate(all_output):
            if interrupt:
                if re.sub("\D", "", interrupt.split()[0]).isdigit():
                    f = open("/proc/irq/" + re.sub("\D", "", interrupt.split()[0]) + "/smp_affinity_list", "r+")
                    print("Attempting to write 0 in /proc/irq/" + re.sub("\D", "",
                                                                         interrupt.split()[0]) + "/smp_affinity_list")
                    f.write(str(0))
                    try:
                        print(interrupt.split()[-1] + " now has affinity " + f.read())
                    except(IOError):
                        print("Could not write 0 in /proc/irq/" + re.sub("\D", "",
                                                                         interrupt.split()[0]) + "/smp_affinity_list\n")
                    f.close()

    if num_cpus > 1:
        print("Setting smp_affinity_list values in /proc/irq/ to spread interrupts across all cores except core 0.")
        for index, interrupt in enumerate(interrupt_output):
            if interrupt:
                f = open("/proc/irq/" + re.sub("\D", "", interrupt.split()[0]) + "/smp_affinity_list", "r+")
                if index + 1 < num_cpus:
                    f.write(str(index + 1))
                else:
                    f.write(str(1) + "-" + str(num_cpus - 1))
                print(interrupt.split()[-1] + " now has affinity " + f.read())

                # TODO: Push other interrupts to core 0.


def setMtu():
    while True:
        print("\nInterface:")
        subprocess.call("ip addr | grep mtu | awk '/mtu/{print $2,$4,$5}'", shell=True)
        print("\n")
        interface = raw_input("What interface do you want to set the mtu for? >> ")
        mtu = raw_input("And what do you want the mtu to be? >> ")
        try:
            subprocess.check_call("ip link set " + interface + " mtu " + mtu, shell=True)
            choice = raw_input("MTU set! Do you want to set another? >> ")
        except(subprocess.CalledProcessError):
            choice = raw_input("Invalid value! Try again? >> ")

        choice = choice.strip().lower()
        if choice == "no" or choice == "n":
            break


def removeBridge():
    while True:
        try:
            subprocess.check_call("sudo ovs-vsctl show", shell=True)
        except(subprocess.CalledProcessError):
            print("OVS is not even installed!")
            break
        bridge = raw_input("\nWhich bridge do you want to remove? >> ")
        subprocess.call("sudo ovs-ofctl show " + bridge, shell=True)
        confirm = raw_input("Are you sure you want to remove bridge " + bridge + "? >> ")
        confirm = confirm.strip().lower()
        if confirm == "yes" or confirm == "y":
            subprocess.call("sudo ovs-vsctl del-br " + bridge, shell=True)
            print("\n" + bridge + " was removed!\n")
            break


def configureOVS():
    # We need to check if OVS is installed first. If it is not, then we should install it.

    try:
        subprocess.check_call("sudo ovs-vsctl show", shell=True)

    except(subprocess.CalledProcessError):
        # TODO: Install OVS.
        print("OVS is not installed! Install OVS and rerun the script. Exiting..")
        exit(1)

    while True:
        print("\nThe public IP for the Clemson controller is '130.127.38.2'..\n")
        controllerIP = raw_input("Please enter controller IP >> ")
        print("\nProbably something similar to '6011'..\n")
        controllerPort = raw_input("Please enter controller OpenFlow port >> ")
        print("\n")
        subprocess.call("ip -o addr show", shell=True)
        print("\n")
        hostInterface = raw_input("Enter the interface that you want to add as a port to this bridge >> ")
        print("\nBe sure to include the subnet. It will probably look like '10.0.0.1/24'..\n")
        hostIP = raw_input("Please enter host IP >> ")
        print("\nFor GENI: 1410\nFor CloudLab: 1500\nWhen using jumbo frames and VLANS: 8974\n")
        mtu = raw_input("Please enter the mtu for the local interface and the bridge >> ")
        print("\nController IP: " + controllerIP)
        print("Controller OpenFlow Port: " + controllerPort)
        print("Host Interface: " + hostInterface)
        print("Host IP: " + hostIP)
        print("Interface and Bridge MTU: " + mtu)
        choice = raw_input("\nIs this correct? >> ")
        choice = choice.strip().lower()
        if choice == "yes" or choice == "y":
            break

    # TODO: Make sure OVS is set to out of band
    print("Building bridge...")
    subprocess.call("sudo ovs-vsctl add-br br0", shell=True)
    subprocess.call("sudo ovs-vsctl add-port br0 " + hostInterface, shell=True)
    subprocess.call("sudo ifconfig " + hostInterface + " 0 up", shell=True)
    subprocess.call("sudo ifconfig br0 " + hostIP + " up", shell=True)
    subprocess.call("sudo ovs-vsctl set-controller br0 tcp:" + controllerIP + ":" + controllerPort, shell=True)
    subprocess.call("sudo ifconfig br0 mtu " + mtu, shell=True)
    subprocess.call("sudo ifconfig " + hostInterface + " mtu " + mtu, shell=True)
    subprocess.call("sudo ovs-vsctl show", shell=True)
    subprocess.call("ifconfig br0", shell=True)


def installAndConfigureAgent():
    print("\nInstalling and configuring the SOS agent!")
    
    print("Installing necessary dependencies!")
    pm = getPackageManager()
    print("Updating...")
    subprocess.call("sudo " + pm + " update -y", shell=True)
    print("Installing clang..")
    subprocess.call("sudo " + pm + " install clang -y", shell=True)
    print("Installing uuid-dev..")
    subprocess.call("sudo " + pm + " install uuid-dev -y", shell=True)
    print("Installing libxml2-dev..")
    subprocess.call("sudo " + pm + " install libxml2-dev -y", shell=True)
    print("Installing zlib1g-dev..")
    subprocess.call("sudo " + pm + " install zlib1g-dev -y", shell=True)
    print("Installing make..")
    subprocess.call("sudo " + pm + " install make -y", shell=True)

    print("Installing the SOS agent..")
    subprocess.call("sudo git clone https://github.com/cbarrin/sos-agent.git", shell=True)

    os.chdir("./sos-agent")
    subprocess.call("ls", shell=True)

    # TODO: Make sure this works for every version of python.
    if sys.version_info[:2] == (2, 6):
        print("Python v2.6 detected. Using Popen.")
        agent_subnet = subprocess.Popen("ip -o addr show br0 | grep -E 'br0.*inet ' | awk '//{print $6}'", shell=True,
                                        stdout=subprocess.PIPE)
        agent_subnet = agent_subnet.communicate()[0]

    else:
        print("Python version greater than v2.6 detected. Using check_output.")
        agent_subnet = subprocess.check_output("ip -o addr show br0 | grep -E 'br0.*inet ' | awk '//{print $6}'",
                                               shell=True)

    # Replace DISCOVERY_DEST_ADDR and STATISTICS_DEST_ADDR with the subnet of 'br0'
    # Two assumptions are made: that the current subnet is '192.168.1.255' and that
    # the bridge is named 'br0'.
    agent_subnet = agent_subnet.strip('\n')
    common_file = fileinput.FileInput('common.h', inplace=True, backup='.bak')
    agent_broadcast = raw_input("Enter the broadcast address for the agent (e.g. 10.0.0.255, 192.168.1.255 etc.) >> ")

    for line in common_file:
        print(line.replace('"' + agent_broadcast + '"', '"' + agent_subnet + '"'))
    common_file.close()

    # Not sure if this will work.. Might have to 'cd'
    subprocess.call("make", shell=True)

    os.chdir("..")
    print("To run the agent, use the command './run.sh'")


def configureEverything():
    # STEP 1: Deleting firewall rules
    deleteFirewallRules()
    # STEP 2: Deleting queueing systems
    deleteQueueingSystems()
    # STEP 3: Configure any network parameters
    configureNetworkParameters()
    # STEP 4: Pin any interrupts to core 0
    pinInterrupts()
    # STEP 5: Install and configure OVS
    configureOVS()
    # STEP 6: Install and configure SOS agent
    installAndConfigureAgent()


def quitProgram():
    exit(1)

def test():
    agent_subnet = subprocess.check_output("ip -o addr show br0 | grep -E 'br0.*inet ' | awk '//{print $6}'",
                                               shell=True)
    agent_subnet = agent_subnet.strip('\n')
    agent_broadcast = raw_input("Enter the broadcast address for the agent (e.g. 10.0.0.255, 192.168.1.255 etc.) >> ")
    print('"' + agent_broadcast + '"')
    print('"' + agent_subnet + '"')


options = {'0': configureEverything,
           '1': deleteFirewallRules,
           '2': deleteQueueingSystems,
           '3': configureNetworkParameters,
           '4': pinInterrupts,
           '5': setMtu,
           '6': removeBridge,
           '7': configureOVS,
           '8': installAndConfigureAgent,
           '9': quitProgram,
           '10': test
           }

while True:
    print("\nSOS CONFIGURATION!")
    print("0: Configure everything!")
    print("1: Delete firewall rules.")
    print("2: Delete queueing systems.")
    print("3: Configure network parameters.")
    print("4: Pin interrupts.")
    print("5: Set MTU.")
    print("6: Remove bridge from OVS.")
    print("7: Configure OVS.")
    print("8: Install and configure the SOS agent.")
    print("9: Quit")

    choice = raw_input("Choose a number to run a module. What do you want to do? >> ")

    try:
        options[choice]()
    except(KeyError):
        print("Invalid key pressed. Choose a number 0-9!")
