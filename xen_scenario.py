#!/usr/bin/env python
# test comment part 2!!!

import XenAPI, sys, re, optparse, random, time

#
# To Do: add switches to avoid menu driven operation to make it possible 
# to spool up multiple scenarios quickly
# 

def get_options():
    parser = optparse.OptionParser('''
Script used to interact with thi XenServer virtual backend. If no options are specified, user will be
given an interactive menu.

-h, --help                          show this help file

-s, --server <server name/ip>       specify the server you would like to connect to

-u, --username <username>           specify the username you would like to connect to

-p, --password <password>           specify the password you would like to use

-n, --scenario <scenario name>      scenario names are defined by which folder VMs are located
                                    in on the XenServer, if this option is not used the script
                                    will enumerate all folders on the server

-v, --vlan <vlan number>            specify what vlan you want to bridge the scenario to, if this
                                    option is not specified you will be prompted to input a vlan
                                    number, any networks with "Uplink" in the description will be
                                    treated as an uplink to be connected to a VLAN, if there is no 
                                    uplink network on the templates this will be unused

-d, --delete                        if this option is specified then  an interactive menu will enumerate
                                    running scenarios to delete


    ''')
    
    parser.add_option('-s', '--server', dest='server', type='string', help='server')
    parser.add_option('-u', '--username', dest='username', type='string', help='username')
    parser.add_option('-p', '--password', dest='password', type='string', help='password')
    parser.add_option('-n', '--scenario', dest='scenario', type='string', help='scenario')
    parser.add_option('-v', '--vlan', dest='vlan', type='string', help='vlan')
    parser.add_option('-d', '--delete', action="store_true", dest="delete", default=False, help='delete')
    parser.add_option('-l', '--list', action="store_true", dest="show_list", default=False, help='show list')
    parser.add_option('-r', '--resource-file', dest='resource_file', type='string', help='resource file')
    parser.add_option('-m', '--preserve-mac', action="store_true", dest="preserve_mac", default=False, help='preserve mac address')
    parser.add_option('--same-server', action="store_true", dest="same_server", default=False, help='start all vms on the same server')

    (options, args) = parser.parse_args()

    server = options.server
    username = options.username
    password = options.password
    vlan = options.vlan
    delete = options.delete
    show_list = options.show_list
    resource_file = options.resource_file
    preserve_mac = options.preserve_mac
    same_server = options.same_server

    # slash required since xenserver's folder value has preceding slash, using try
    # block since this will error if --scenario is not passed

    try:
        scenario = '/' + options.scenario
    except:
        scenario = None

    return server, username, password, scenario, vlan, delete, show_list, resource_file, preserve_mac, same_server

def get_session(server, username, password):
    
    # creating a session with server
    if (server[:6] == 'http://' or server[:7] == 'https://'):
        session = XenAPI.Session(server)
    else:
        session = XenAPI.Session('http://' + server)

    session.xenapi.login_with_password(username, password)

    return session

def get_scenario(session, folders):
    
    # menu driven, select from available scenarios
    # here we are finding all unique folder names, if a vm is not assigned in a folder
    # our code will error so we put it in a try block
    # now we need to print a menu for the user to select
    
    count = 1
    print '\n'

    for folder in folders:
        # starting from index 1 to get rid of the leading slash
        print str(count) + ":  " + folder[1:]
        count += 1
    
    choice = raw_input('\n\nPlease select a scenario:  ')
    scenario = folders[int(choice)-1]
    return scenario, folder

def get_vlan():
    vlan = raw_input('\n\nPlease select a VLAN you want to connect this scenario to:  ') 
    return vlan

def get_templates(session, scenario, vms):
    templates = []

    for vm in vms:
        try:
            # we are looking for all vms that are in our scenarios folder
            vm_rec = session.xenapi.VM.get_record(vm)
            if vm_rec['other_config']['folder'] == scenario and vm_rec['is_a_snapshot'] == False:
                # we want to filter out any VMs that end with dash and three digits, we 
                # assume that no template VM would be named like this, there is probably a 
                # more reliable way to do this
                if not re.search(r'[0-9][0-9][0-9]', session.xenapi.VM.get_record(vm)['name_label'][:3]):
                    templates.append(vm)
        except Exception, e:
		pass	

    return templates

def get_unique_id(session, vms):
    
    count = 0
    # var starts out true so the while loop executes at least once
    not_unique = True
    
    # while we have not found a unique number...
    while not_unique:
        count += 1
        # we start our loop with the assumption that this is a unique number
        not_unique = False
        for vm in vms:
            # if the last 4 chars of the vms name match our current count padded with zeros,
            # then we set not_unique to True and break out of our loop, count is incremented and
            # we try again
            if session.xenapi.VM.get_record(vm)['name_label'][:3] == str(count).zfill(3):
                not_unique = True
                break
    # now that we have made it out of our while loop with a unique count number, we have to zero pad
    # it and return it as a string
    unique_id = str(count).zfill(3)
    return unique_id


def create_clones(session, templates, unique_id):
    # now we take our template list, clone each vm and append it's name with our unique_id, this function
    # returns a list of our new clones
    clones = []
    for vm in templates:
        vm_rec = session.xenapi.VM.get_record(vm)
        new_name = unique_id + '---' + vm_rec['name_label']
        print "Cloning " + session.xenapi.VM.get_record(vm)['name_label'] + ' to ' + new_name
        clone = session.xenapi.VM.clone(vm, new_name)
        clones.append(clone)
	clone_vm_rec = session.xenapi.VM.get_record(clone)
        # deleting clone interfaces
        for vif in clone_vm_rec['VIFs']:
            session.xenapi.VIF.destroy(vif)
        # adding template interfaces to clone to preserve MAC address
        for vif in vm_rec['VIFs']:
            vif_rec = session.xenapi.VIF.get_record(vif)
            vif_rec['VM'] = clone
            session.xenapi.VIF.create(vif_rec)
    print '\n'
    return clones


def network_type(session, vif_rec):
    net_rec = session.xenapi.network.get_record(vif_rec['network'])
    if net_rec['PIFs']:
        pif_rec = session.xenapi.PIF.get_record(net_rec['PIFs'][0])
        if pif_rec['device'].startswith('tunnel'):
            return 'CSPN'
        elif pif_rec['device'].startswith('eth'):
            if pif_rec['VLAN'] == '-1':
                return "bridged"
            else:
                return "VLAN"
    else:
        if net_rec['bridge'] == 'xenapi':
            return "MGMT"
        else:
            return "SSPN"


def config_networking(session, clones, unique_id, vlan, preserve_mac):
    
    mgmt_device = 'eth0'
    trunk_device = 'eth1'
    mgmt_pifs = []
    trunk_pifs = []
    new_networks = []
    
    for pif in session.xenapi.PIF.get_all():
        if (session.xenapi.PIF.get_record(pif)['device'] == 'eth0' and\
            session.xenapi.PIF.get_record(pif)['VLAN'] == '-1'):
            mgmt_pifs.append(pif)

        elif session.xenapi.PIF.get_record(pif)['device'] == 'eth1':
            trunk_pifs.append(pif)
        
    for vm in clones:
        vm_rec = session.xenapi.VM.get_record(vm)
        for vif in vm_rec['VIFs']:
            vif_rec = session.xenapi.VIF.get_record(vif)
            net_type = network_type(session, vif_rec)
            net_rec = session.xenapi.network.get_record(vif_rec['network'])
            if net_type == 'bridged':
                # networks bridged to a physical interface we leave alone
                continue
            elif net_type == 'VLAN' and not vlan:
                # if vlan is not specified we leave it alone
                continue
            elif net_type == 'VLAN' and vlan:
                # need to add creation of vlan tagged networks
                continue
            elif net_type == 'CSPN' or net_type == 'SSPN':
                session.xenapi.VIF.destroy(vif)

                # creating new network
                net_rec['name_label'] = unique_id + '---' + net_rec['name_label']
                new_net = session.xenapi.network.get_by_name_label(net_rec['name_label'])
                if new_net:
                    # if network existed, we have a list with one item, need string
                    new_net = new_net[0]
                else:
                    del net_rec['VIFs']
                    del net_rec['uuid']
                    new_net = session.xenapi.network.create(net_rec)
                    new_networks.append(net_rec['name_label'])
                    if net_type == 'CSPN':
                        for pif in mgmt_pifs:
                            session.xenapi.tunnel.create(pif, new_net)
                # creating vif and attaching to new network
                vif_rec['network'] = new_net
                vif_rec['VM'] = vm
                if not preserve_mac:
                    mac = "01:02:03:%02x:%02x:%02x" % (\
                            random.randint(0, 255),\
                            random.randint(0, 255),\
                            random.randint(0, 255))
                    vif_rec['MAC'] = mac
                session.xenapi.VIF.create(vif_rec)

            else:
                print "Unknown network type: " + net_type
    return new_networks


def delete_scenario(resource_file, session):
    # enumerate resource files!?!?!, I think so!
    with open(resource_file) as f:
        resource_file = f.readlines()
    for line in resource_file:
        if line.startswith('vm:'):
            try:
                # delete vms
                vm = session.xenapi.VM.get_by_name_label(line[3:].rstrip('\n'))[0]
                vm_rec = session.xenapi.VM.get_record(vm)
                print "Deleting: " + vm_rec['name_label']
                if not vm_rec['power_state'] == "Halted":
                    session.xenapi.VM.hard_shutdown(vm)
                session.xenapi.VM.destroy(vm)
            except:
                print "Error deleting {0}".format(line[3:])
        elif line.startswith('net:'):
            try:
                net = session.xenapi.network.get_by_name_label(line[4:].strip('\n'))[0]
                net_rec = session.xenapi.network.get_record(net)
                print "Deleting: " + net_rec['name_label']
                if net_rec['PIFs']:
                    pif_rec = session.xenapi.PIF.get_record(net_rec['PIFs'][0])
                    if pif_rec['device'].startswith('tunnel'):
                        for pif in net_rec['PIFs']:
                            pif_rec = session.xenapi.PIF.get_record(pif)
                            session.xenapi.tunnel.destroy(pif_rec['tunnel_access_PIF_of'][0])
                session.xenapi.network.destroy(net)
            except:
                print "Error deleting {0}".format(line[4:])
        else:
            print "Unexpected line in resource file:\n" + line


def write_resource_file(session, clones, unique_id, vlan, new_networks):
    file_name = unique_id + '.resource.txt'
    with open(file_name, 'w') as f:
	for vm in clones:
            f.write('vm:' + session.xenapi.VM.get_record(vm)['name_label'] + '\n')
	for net in new_networks:
            f.write('net:' + net + '\n')


def get_folders(session, vms):
    folders = []
    for vm in vms:
        try:
            folder = session.xenapi.VM.get_record(vm)['other_config']['folder']
            if folder not in folders:
                folders.append(folder)
        except:
            pass
    return folders

def start_vms(clones, session, same_server):
    # allowing xen to determine best server to start first VM
    session.xenapi.VM.start(clones[0], False, True)
    vm_rec = session.xenapi.VM.get_record(clones[0])
    host = vm_rec['resident_on']

    # trying really hard to start VMs
    for vm in clones[1:]:
        vm_rec = session.xenapi.VM.get_record(vm)
        try:
            for i in range(3):
                if same_server:
                    session.xenapi.VM.start_on(vm, host, False, True)
                    print "Starting " + vm_rec['name_label']
                else:
                    session.xenapi.VM.start(vm, False, True)
        except Exception, e:
            #print e
            pass
    pass

def main():
    
    server, username, password, scenario, vlan, delete, show_list, resource_file, preserve_mac, same_server = get_options()
    
    # include switches to pass info directly 
    if not server:
        server = "127.0.0.1"

    if not username:
        username = "root"

    if not password:
        password = "password"
    
    session = get_session(server, username, password)
    
    if delete and not resource_file:
        print "You must specify a resource file when passing the delete option"
        exit(0)

    elif delete:
        # check to see if the delete switch has been passed, if true check to see if unique_id
        # or vlan has been passed, if not the menu driven enumerate running scenarios and allow
        # user to select which will be deleted
        delete_scenario(resource_file, session)

    else: 
        # getting all vms currently in this pool
        vms = session.xenapi.VM.get_all()
	        
        # enumerating scenarios, pulled out of get scenario so we can use this info with the 
        # --list option
        folders = get_folders(session, vms)

        # if the --list flag was passed, iterate through folders and print a list of available 
        # arguments to the --scenario option, exit(0) so we will exit ignoring any other options
        # that have been passed
        if show_list:
            print '\n'
            for folder in folders:
                print folder[1:]
            print '\n'
            exit(0)
        
        # if a scenario name was not passed using --scenario, prompt for user input
        if not scenario:
            scenario = get_scenario(session, folders)
        
        # if a vlan number was not pass through --vlan, prompt for user input
        if not vlan:
            vlan = '-1'
        
        # get a list of the base 'templates' that will be cloned out to make a unique scenario
        templates = get_templates(session, scenario, vms)
        
        # find a unique number in this pool to prepend to all scenario vms that we spool up
        unique_id = get_unique_id(session, vms)

        # this is where the template vms are cloned and the scenario vms are created
        clones = create_clones(session, templates, unique_id)
        
        # we enumerate all networks attached to the clones and modify them with the unique id
        # !NEEDS WORK!
        new_networks = config_networking(session, clones, unique_id, vlan, preserve_mac)
        
        # write an info file with vm names, new networks, and vlan information
        write_resource_file(session, clones, unique_id, vlan, new_networks)
        
        start_vms(clones, session, same_server)
if __name__ == '__main__':
    main()

