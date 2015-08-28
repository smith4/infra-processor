#
# Copyright (C) 2014 MTA SZTAKI
#

""" Basic Infrastructure Processor for OCCO

.. moduleauthor:: Adam Visegradi <adam.visegradi@sztaki.mta.hu>
"""

__all__ = ['BasicInfraProcessor',
           'CreateInfrastructure', 'CreateNode', 'DropNode', 'DropInfrastructure']

import logging
import occo.util.factory as factory
import occo.infobroker as ib
import occo.infobroker.eventlog
from occo.infraprocessor.node_resolution import resolve_node
import sys
import uuid
import yaml
from occo.infraprocessor import InfraProcessor, Command
from occo.infraprocessor.strategy import Strategy
from occo.exceptions.orchestration import *

log = logging.getLogger('occo.infraprocessor.basic')
datalog = logging.getLogger('occo.data.infraprocessor.basic')

###############
## IP Commands

class CreateInfrastructure(Command):
    """
    Implementation of infrastructure creation using a
    :ref:`service composer <servicecomposer>`.

    :param str infra_id: The identifier of the infrastructure instance.

    The ``infra_id`` is a unique identifier pre-generated by the
    :ref:`Compiler <compiler>`. The infrastructure will be instantiated with
    this identifier.
    """
    def __init__(self, infra_id):
        Command.__init__(self)
        self.infra_id = infra_id

    def perform(self, infraprocessor):
        try:
            log.debug('Creating infrastructure %r', self.infra_id)
            result = infraprocessor.servicecomposer.create_infrastructure(
                self.infra_id)
            ib.main_eventlog.infrastructure_created(self.infra_id)
        except KeyboardInterrupt:
            # A KeyboardInterrupt is considered intentional cancellation
            log.info('Cancelling infrastructure creation (received SIGINT)')
            self._undo_create_infra(infraprocessor)
            raise
        except InfraProcessorError:
            # This is a pre-cooked exception, no need for transformation
            raise
        except Exception as ex:
            log.exception('Error while creating infrastructure %r:',
                          self.infra_id)
            raise InfrastructureCreationError(self.infra_id, ex), \
                None, sys.exc_info()[2]
        else:
            return result

    def _undo_create_infra(self, infraprocessor):
        try:
            log.info('UNDOING infrastructure creation: %r', self.infra_id)
            cmd = infraprocessor.cri_drop_infrastructure(self.infra_id)
            cmd.perform(infraprocessor)
        except Exception:
            # This exception is ignored for the following reason:
            # The actual command that is running now is a CreateXXX command;
            # undoing is triggered only upon an exception while performing that
            # command. Towards the caller, the original exception must be
            # propagated, not this auxiliary error.
            log.exception(
                'IGNORING exception while undoing {0}:'.format(self.__class__))

class CreateNode(Command):
    """
    Implementation of node creation using a
    :ref:`service composer <servicecomposer>` and a
    :ref:`cloud handler <cloudhandler>`.

    :param node: The description of the node to be created.
    :type node: :ref:`nodedescription`

    """
    def __init__(self, node_description):
        Command.__init__(self)
        self.node_description = node_description

    def perform(self, infraprocessor):
        node_description = self.node_description

        log.debug('Creating node %r', node_description['name'])
        datalog.debug('Performing CreateNode on node {\n%s}',
                      yaml.dump(node_description, default_flow_style=False))

        instance_data = dict(
            node_id=str(uuid.uuid4()),
            infra_id=node_description['infra_id'],
            user_id=node_description['user_id'],
            node_description=node_description,
        )

        log.info('Creating node %r', instance_data['node_id'])

        try:
            self._perform_create(infraprocessor, instance_data)
            ib.main_eventlog.node_created(instance_data)
        except KeyboardInterrupt:
            # A KeyboardInterrupt is considered intentional cancellation
            log.info('Cancelling node creation (received SIGINT)')
            self._undo_create_node(infraprocessor, instance_data)
            raise
        except NodeCreationError as ex:
            # Amend a node creation error iff it couldn't have been initialized
            # properly at the point of raising it.
            if not ex.instance_data:
                ex.instance_data = instance_data
            raise
        except InfraProcessorError:
            # This is a pre-cooked exception, no need for transformation
            raise
        except Exception as ex:
            log.exception('Error while creating node %r:',
                          instance_data['node_id'])
            raise NodeCreationError(instance_data, ex), None, sys.exc_info()[2]
        else:
            log.info("Node %s/%s/%s has started",
                     node_description['infra_id'],
                     node_description['name'],
                     instance_data['node_id'])
            return instance_data

    def _perform_create(self, infraprocessor, instance_data):
        """
        Core to :meth:`perform`. only to avoid a level of nesting.
        """

        # Quick-access references
        node_id = instance_data['node_id']
        ib = infraprocessor.ib
        node_description = self.node_description

        # Resolve all the information required to instantiate the node using
        # the abstract description and the UDS/infobroker
        resolved_node_def = resolve_node(
            ib, node_id, node_description,
            getattr(infraprocessor, 'default_timeout', None)
        )
        datalog.debug("Resolved node description:\n%s",
                      yaml.dump(resolved_node_def, default_flow_style=False))
        instance_data['resolved_node_definition'] = resolved_node_def
        instance_data['backend_id'] = resolved_node_def['backend_id']

        # Create the node based on the resolved information
        infraprocessor.servicecomposer.register_node(resolved_node_def)
        instance_id = infraprocessor.cloudhandler.create_node(resolved_node_def)
        instance_data['instance_id'] = instance_id

        import occo.infraprocessor.synchronization as synch

        log.debug('Registering node instance_data for node %s/%s/%s',
                  node_description['infra_id'],
                  node_description['name'],
                  instance_data['node_id'])
        infraprocessor.uds.register_started_node(
            node_description['infra_id'],
            node_description['name'],
            instance_data)

        log.info(
            "Node %s/%s/%s has been started successfully",
            node_description['infra_id'],
            node_description['name'],
            node_id
        )
        log.info(
            "Address of node %s/%s/%s: %r (%s)",
            node_description['infra_id'],
            node_description['name'],
            node_id,
            ib.get('node.resource.address', instance_data),
            ib.get('node.resource.ip_address', instance_data)
        )

        synch.wait_for_node(instance_data,
                            infraprocessor.poll_delay,
                            resolved_node_def['create_timeout'])

        return instance_data

    def _undo_create_node(self, infraprocessor, instance_data):
        try:
            log.info('UNDOING node creation: %r', instance_data['node_id'])
            cmd = infraprocessor.cri_drop_node(instance_data)
            cmd.perform(infraprocessor)
        except Exception:
            # This exception is ignored for the following reason:
            # The actual command that is running now is a CreateXXX command;
            # undoing is triggered only upon an exception while performing that
            # command. Towards the caller, the original exception must be
            # propagated, not this auxiliary error.
            log.exception(
                'IGNORING exception while undoing {0}:'.format(self.__class__))

class DropNode(Command):
    """
    Implementation of node deletion using a
    :ref:`service composer <servicecomposer>` and a
    :ref:`cloud handler <cloudhandler>`.

    :param instance_data: The description of the node instance to be deleted.
    :type instance_data: :ref:`instancedata`

    """
    def __init__(self, instance_data):
        Command.__init__(self)
        self.instance_data = instance_data

    def perform(self, infraprocessor):
        try:
            log.debug('Dropping node %r', self.instance_data['node_id'])
            infraprocessor.cloudhandler.drop_node(self.instance_data)
            infraprocessor.servicecomposer.drop_node(self.instance_data)
            ib.main_eventlog.node_deleted(self.instance_data)
        except KeyboardInterrupt:
            # A KeyboardInterrupt is considered intentional cancellation
            raise
        except InfraProcessorError:
            # This is a pre-cooked exception, no need for transformation
            raise
        except Exception as ex:
            log.exception('Error while dropping node %r:',
                          self.instance_data['node_id'])
            raise \
                MinorInfraProcessorError(
                    self.instance_data['infra_id'],
                    ex,
                    instance_data=self.instance_data), \
                None, sys.exc_info()[2]

class DropInfrastructure(Command):
    """
    Implementation of infrastructure deletion using a
    :ref:`service composer <servicecomposer>`.

    :param str infra_id: The identifier of the infrastructure instance.
    """
    def __init__(self, infra_id):
        Command.__init__(self)
        self.infra_id = infra_id

    def perform(self, infraprocessor):
        try:
            log.debug('Dropping infrastructure %r', self.infra_id)
            infraprocessor.servicecomposer.drop_infrastructure(self.infra_id)
            ib.main_eventlog.infrastructure_deleted(self.infra_id)
        except KeyboardInterrupt:
            # A KeyboardInterrupt is considered intentional cancellation
            raise
        except InfraProcessorError:
            # This is a pre-cooked exception, no need for transformation
            raise
        except Exception as ex:
            log.exception('Error while dropping infrastructure %r:',
                          self.infra_id)
            raise MinorInfraProcessorError(self.infra_id, ex), \
                None, sys.exc_info()[2]

####################
## IP implementation

@factory.register(InfraProcessor, 'basic')
class BasicInfraProcessor(InfraProcessor):
    """
    Implementation of :class:`InfraProcessor` using the primitives defined in
    this module.

    :param user_data_store: Database manipulation.
    :type user_data_store: :class:`~occo.infobroker.UDS`

    :param cloudhandler: Cloud access.
    :type cloudhandler: :class:`~occo.cloudhandler.cloudhandler.CloudHandler`

    :param servicecomposer: Service composer access.
    :type servicecomposer:
        :class:`~occo.servicecomposer.servicecomposer.ServiceComposer`

    :param process_strategy: Plug-in strategy for performing an independent
        batch of instructions.
    :type process_strategy: :class:`Strategy`

    :param int poll_delay: Node creation is synchronized on the node becoming
        completely operational. This condition has to be polled in
        :meth:`CreateNode.perform`. ``poll_delay`` is the number of seconds to
        wait between polls.
    """
    def __init__(self, user_data_store,
                 cloudhandler, servicecomposer,
                 process_strategy='sequential',
                 poll_delay=10,
                 **config):
        super(BasicInfraProcessor, self).__init__(
            process_strategy=process_strategy)
        self.__dict__.update(config)
        self.ib = ib.main_info_broker
        self.uds = user_data_store
        self.cloudhandler = cloudhandler
        self.servicecomposer = servicecomposer
        self.poll_delay = poll_delay

    def cri_create_infrastructure(self, infra_id):
        return CreateInfrastructure(infra_id)

    def cri_create_node(self, node_description):
        return CreateNode(node_description)

    def cri_drop_node(self, instance_data):
        return DropNode(instance_data)

    def cri_drop_infrastructure(self, infra_id):
        return DropInfrastructure(infra_id)
