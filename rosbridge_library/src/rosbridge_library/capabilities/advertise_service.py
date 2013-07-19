import importlib        # TODO: try to use ros_loader instead of import blabla
from rosbridge_library.capability import Capability
import rospy
from rosbridge_library.internal.ros_loader import get_service_class
from datetime import datetime
import time
try:
    import threading
except AttributeError, e:
    print "hier"
try:
    import ujson as json
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        import json


class ServiceList():
    """
    Singleton class to hold lists of received fragments in one 'global' object
    """
    class __impl:
        """ Implementation of the singleton interface """
        def spam(self):
            """ Test method, return singleton id """
            return id(self)

    __instance = None
    list = {}

    def __init__(self):
        """ Create singleton instance """
        if ServiceList.__instance is None:
            ServiceList.__instance = ServiceList.__impl()
            self.list = {}

        self.__dict__['_ServiceList__instance'] = ServiceList.__instance

    def __getattr__(self, attr):
        """ Delegate access to implementation """
        return getattr(self.__instance, attr)

    def __setattr__(self, attr, value):
        """ Delegate access to implementation """
        return setattr(self.__instance, attr, value)


class ReceivedResponses():
    """
    Singleton class to hold lists of received fragments in one 'global' object
    """
    class __impl:
        """ Implementation of the singleton interface """
        def spam(self):
            """ Test method, return singleton id """
            return id(self)

    __instance = None
    list = {}

    def __init__(self):
        """ Create singleton instance """
        if ReceivedResponses.__instance is None:
            ReceivedResponses.__instance = ReceivedResponses.__impl()
            self.list = {}

        self.__dict__['_ReceivedResponses__instance'] = ReceivedResponses.__instance

    def __getattr__(self, attr):
        """ Delegate access to implementation """
        return getattr(self.__instance, attr)

    def __setattr__(self, attr, value):
        """ Delegate access to implementation """
        return setattr(self.__instance, attr, value)



class ROS_Service_Template( threading.Thread):
    service_request_timeout = 15 #seconds
    check_response_delay = 0.1 #seconds

    service_name = None
    service_node_name = None
    service_module = None
    service_type = None
    client_callback = None

    client_id = None
    service_id = None

    ros_serviceproxy = None

    request_counter = 0
    request_list = {}     # holds requests until they are answered (response successfully sent to ROS-client)
                          # ..probably not needed, but maybe good for retransmission of request or s.th. similar
    response_list = ReceivedResponses().list    # holds service_responses until they are sent back to ROS-client
                                                # .. links to singleton

    finish_flag = False
    busy = False

    def __init__(self, client_callback, service_module, service_type, service_name, client_id):
        threading.Thread.__init__(self)

        
        #print " ROS_Service_Template used to create a rosbridge-ServiceInstance"
        self.service_name = service_name
        self.service_module = service_module
        self.service_type = service_type
        self.client_id = client_id
        self.client_callback = client_callback
        
        self.spawn_ROS_service( service_module, service_type, service_name, client_id)



    def handle_service_request(self, req):
        while not self.spawned or self.busy:
            #print "waiting for busy service provider; spawned?", self.spawned, "busy?", self.busy
            # if stop_Service was called.. kill unsent requests to that service
            if self.finish_flag:
                return None
            # wait for delay_between requests to allow the currently working request to be finished..
            time.sleep(0.1)

        self.busy = True
#        print "----------------------------------------------------------------"
#        print  "handle_service_request called"
#        print "  service_request:"
#        print req
#        print "  service_name:", self.service_name
#        print "  service_type:", self.service_type
#        print "  service providing client_id:", self.client_id
#
#        print "  client_callback:" , self.client_callback

        # generate request_id
        request_id = "count:"+str(self.request_counter)+"_time:" +datetime.now().strftime("%H:%M:%f")
        self.request_counter = (self.request_counter + 1) % 500000  # TODO modulo blabla..

        # TODO: check for more complex parameter and types and bla --> need better parser!
        # --> see message_conversion
        args_list = str(req).split("\n")
        args_dict = {}
        for arg in args_list:
            key, value = arg.split(":")
            args_dict[key] = value

        request_message_object = {"op":"service_request",                                   # advertise topic
                                    "request_id": request_id,
                                    "service_type": self.service_type,
                                    "service_name": self.service_name,
                                    "args": args_dict
                                    }
        request_message = json.dumps(request_message_object)

        #print " request_message:", request_message

        # TODO: check cases! this cond should not be necessary
        if request_id not in self.request_list.keys():
            self.request_list[request_id] = request_message_object



        answer = None
        try:
            # TODO: better handling of multiple request; only use one main handler for each service
            #self.busy = True
            #time.sleep(0.1)
            self.client_callback (request_message_object)
            
            #print " sent request to client that serves the service"

            # TODO: add timeout to this loop! remove request_id from request_list after timeout!
            begin = datetime.now()
            duration = datetime.now() - begin

            # if stop_service was called.. stop waiting for response
            while not self.finish_flag and request_id not in self.response_list.keys() and duration.total_seconds() < self.service_request_timeout:
                #print " waiting for response to request_id:", request_id
                time.sleep(self.check_response_delay)
                duration = datetime.now() - begin

            if request_id in self.response_list:
                #print "  response_list:", self.response_list
                #print "  request_list:", self.request_list
                answer = self.response_list[request_id]
                del self.response_list[request_id]

            else:
                # request failed due to timeout
                print "request timed out!"
                answer = None
            del self.request_list[request_id]
            #print "----------------------------------------------------------------"
            
        except Exception, e:
            print e

        #print "answer is None?:",answer == None
        # block before leaving and allowing next request, if request did not time out..
        #time.sleep(0.1)
        self.busy = False

        return answer


    def stop_ROS_service(self):
        print " stopping ROS service"
        self.spawned = False
        self.finish_flag = True
        self.ros_serviceproxy.shutdown("reason: stop service requested")

        # wait for request_loops to run into finish_flags
        for request_id in self.request_list.keys():
            self.response_list[request_id] = None
        time.sleep(3)

        # inform client that service is not active anymore
        # ..try to close tcp-socket
        service_list = ServiceList().list
        del service_list[self.service_name]

        # inform client that service had been stopped
        try:
            self.client_callback ({"values":None})
        except Exception, e:
            pass
        
        

    

    spawned = False
    def spawn_ROS_service(self, service_module, service_type, service_name, client_id):
        #print " spawn_ROS_service called"
        try:

            #exec("from rosbridge_library import srv.SendBytes")
            #print "from", "rosbridge_library", "import", "srv"

            print "from", service_module, "import", service_type
            #exec("from " + service_module + " import " + service_type)
            #print "  import of",service_type, "from", service_module, "succeeded!"
        except Exception, e:
            print "  import of",service_type, "from", service_module, "FAILED!"
            print e

        some_module = importlib.import_module(service_module)
        self.ros_serviceproxy = rospy.Service( service_name, getattr(some_module, service_type), self.handle_service_request)

        # try to use ros_loader instead of "import .." stuff above
#        ros_service_type = get_service_class(service_type)
#        self.ros_serviceproxy = rospy.Service( service_name, ros_service_type, self.handle_service_request)
        
        print " ROS service spawned."
        print "  client_id:", self.client_id
        print "  service-name:", self.service_name
        print "  service-type:", self.service_type
        self.spawned = True


class AdvertiseService(Capability):

    opcode_advertise_service = "advertise_service"      # rosbridge-client -> rosbridge # register in protocol.py!
    service_list = ServiceList().list                   # links to singleton


    def __init__(self, protocol):
        self.protocol = protocol
        Capability.__init__(self, protocol)
        protocol.register_operation(self.opcode_advertise_service, self.advertise_service)


    def advertise_service(self, message):
        #print "advertise_service called:"
        #print "  client_id:", self.protocol.client_id
        # register client internal with service to allow routing of service requests
        #print "  ", message
        opcode = message["op"]
        service_type = message["service_type"]
        service_name = message["service_name"]
        service_module = message["service_module"]
        client_id = self.protocol.client_id
        client_callback = self.protocol.send
        # TODO: define what happens when existing service gets advertised
        if service_name not in self.service_list.keys():
            #print " registering new service, did not exist before.."
            self.service_list[service_name] = ROS_Service_Template(client_callback , service_module, service_type, service_name, client_id)
        else:
            print " replacing existing service"
            self.service_list[service_name].stop_ROS_service()
            #del self.service_list[service_name]
            self.service_list[service_name] = ROS_Service_Template(client_callback , service_module, service_type, service_name, client_id)

        #print "  self.service_list:", self.service_list

    def finish(self):
        self.finish_flag = True
        self.protocol.unregister_operation("advertise_service")