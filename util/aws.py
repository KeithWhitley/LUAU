import boto3
import logging
import json

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

LOW_USE_CHECK_ID = 'Qch7DwouX1'
SES_EMAIL = 'keithw@sahajsoft.com'
ADMIN_EMAIL = 'keithw@sahajsoft.com'


class EC2Wrapper:
    def __init__(self, session):
        self.session = session
        self.ec2 = session.client('ec2')

    def create_tags(self, Resources, Tags):
        return self.ec2.create_tags(
            Resources=Resources,
            Tags=Tags
        )

    def tag_as_low_use(self, instance_id): 
        return self.tag_instance(instance_id, 'Low Use', 'true')

    def tag_as_whitelisted(self, instance_id):
        return self.tag_instance(instance_id, 'Whitelisted', 'true')
    
    def tag_whitelist_reason(self, instance_id, reason):
        return self.tag_instance(instance_id, 'Reason', reason)

    def tag_for_deletion(self, instance_id):
        return self.tag_instance(instance_id, 'Scheduled For Deletion', 'true')
        
    def tag_instance(self, instance_id, tag_key, tag_value):
        tag = {
            'Key': tag_key,
            'Value': tag_value
        }
        return self.ec2.create_tags(
            Resources=[instance_id],
            Tags=[tag]
        )

    def get_creator_for_instance(self, instance_id):
        return self.get_tag_for_instance(instance_id, 'Creator')

    def get_whitelist_reason_for_instance(self, instance_id):
        if self.is_whitelisted(instance_id):
            return self.get_tag_for_instance(instance_id, 'Reason')
        else:
            return None


    def get_tag_for_instance(self, instance_id, tag_key):
        tags = self.get_tags_for_instance(instance_id)
        for tag in tags:
            if tag['Key'] == tag_key:
                return tag['Value']
        return None

    def get_tags_for_instance(self, instance_id):
        response = self.ec2.describe_instances(InstanceIds=[instance_id])
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                if instance['InstanceId'] == instance_id:
                    return instance['Tags']
        return []

    def is_whitelisted(self, instance_id):
        return self.is_tagged(instance_id, 'Whitelisted')

    def is_low_use(self, instance_id):
        return self.is_tagged(instance_id, 'Low Use')

    def is_scheduled_for_deletion(self, instance_id):
        return self.is_tagged(instance_id, 'Scheduled For Deletion')

    def is_tagged(self, instance_id, tag_name):
        tag_value = self.get_tag_for_instance(instance_id, tag_name)
        if tag_value is not None and tag_value == 'true':
            return True
        else:
            return False


class ASGWrapper:
    def __init__(self, session):
        self.session = session
        self.asg = session.client('autoscaling')

    def get_asg_user_tag_by_instance_id(self, instance_ids):
        """Get the name of the ASG for these instances

        This is done to ensure that the owner of the ASG is accurated tagged as the owner
        of the instances belonging to the ASG

        Params:
            instance_ids ([str]): List of instance_ids that belong to the same ASG
        Returns:
            str: The ASG Name associated with these instances
        """
        # Use the first instance because all of them will belong to the same ASG
        instance_id = instance_ids[0]
        instance_data = self.asg.describe_auto_scaling_instances(InstanceIds=[instance_id])
        try:
            return instance_data['AutoScalingInstances'][0]['AutoScalingGroupName']
        except KeyError as e:
            logger.warning('Instance does not exist: %s', str(e))
        except Exception as e:
            logger.error('Unknown Error: %s', str(e))

    def get_asg_instance_ids(self, asg_name):
        """Get the instance_ids of instances belonging to an ASG

        Params:
            asg_name (str): Name of an ASG
        Returns:
            [str]: List of ids of instances in the ASG

        """
        instance_ids = []
        # Grab the first item in the list because we're only asking for 1 ASG
        asg_data = self.asg.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name])['AutoScalingGroups'][0]

        for instance_data in asg_data['Instances']:
            instance_ids.append(instance_data['InstanceId'])

        return instance_ids

    def create_or_update_tags(self, Tags):
        tag = Tags[0]
        asg_name = tag['ResourceId']
        ec2_tag = {
            'Key': tag['Key'],
            'Value': tag['Value']
        }
        try:
            response = self.asg.create_or_update_tags(
                Tags=Tags
            )
        except Exception as e:
            logger.error('Unknown Error: %s', str(e))
        else:
            logger.info(response)

        asg_instances = self.get_asg_instance_ids(asg_name)
        return EC2Wrapper(self.session).create_tags(Resources=asg_instances, Tags=[ec2_tag])


class TrustedAdvisor:
    def __init__(self):
        self.support = boto3.client('support', region_name='us-east-1')

    def get_low_use_instances(self):
       response = self.support.describe_trusted_advisor_check_result(checkId=LOW_USE_CHECK_ID, language='en')
       if 'result' in response:
           return response['result'].get('flaggedResources', [])

    def get_low_use_summary(self):
        response = self.support.describe_trusted_advisor_check_summaries(checkIds=[LOW_USE_CHECK_ID])
        for checks in response.get('summaries', []):
            if checks['checkId'] == LOW_USE_CHECK_ID:
                return checks
        return None


class DynamoWrapper:
    """
    Handler for dynamodb data
    """
    def __init__(self, session):
        self.session = session
        self.dynamo = session.resource('dynamodb')
        self.low_use = self.dynamo.Table('LowUse')
        self.whitelist = self.dynamo.Table('Whitelist')

    def get_whitelist_instance(self, instance_id):
        """
        Fetch Instance from whitelist table.
        """
        key = {"InstanceID": instance_id}
        return self.whitelist.get_item(Key=key)

    def get_low_use_instance(self, instance_id):
        """
        Fetch instance from whitelist table
        """
        key = {"InstanceID": instance_id}
        return self.low_use.get_item(Key=key)

    def is_whitelisted(self, instance_id):
        item = self.get_whitelist_instance(instance_id)
        if item is None:
            return False
        else:
            return True

    def is_low_use(self, instance_id):
        item = self.get_low_use_instance(instance_id)
        if item is None:
            return False
        else:
            return True

    def is_scheduled_for_deletion(self, instance_id):
        item = self.get_low_use_instance(instance_id)
        if item is not None:
            return item.get('Scheduled For Deletion', False)

    def add_to_whitelist(self, instance_id, creator, reason):
        item = {
            "InstanceID": instance_id,
            "Creator": creator,
            "Reason": reason,
            "EmailSent": False
        }
        self.delete_from_low_use(instance_id)
        response = self.whitelist.put_item(Item=item)
        return response

    def add_to_low_use(self, instance_id, creator):
        item = {
            "InstanceID": instance_id,
            "Creator": creator,
            "Scheduled For Deletion": False,
            "EmailSent": False
        }

        return self.low_use.put_item(Item=item)

    def schedule_for_deletion(self, instance_id, creator):
        item = {
            "InstanceID": instance_id,
            "Creator": creator,
            "Scheduled For Deletion": True
        }

        return self.low_use.put_item(Item=item)


    def delete_from_low_use(self, instance_id):
        key = {"InstanceID": instance_id}
        return self.low_use.delete_item(Key=key)

class SESWrapper:
    def __init__(self, session):
        self.session = session
        self.ses = session.client('ses')
        self.low_use_template_name = 'LowUseReport'
        self.admin_template_name = 'AdminLowUseReport'

    def get_low_use_template_data(self, creator, low_use_instances, instances_scheduled_for_deletion):
        template_data = {
            'creator': creator,
            'creator_name': creator.split('@')[0],
            'instance': []
        }

        for instance in low_use_instances:
            if instance['Creator'] is None:
                instance['Creator'] = 'Unknown'
            instance_data = {
                'instance_id': instance['InstanceID'],
                'instance_creator': instance['Creator'],
                'scheduled_for_deletion': False,
                'cost': instance['Cost'],
                'average_cpu_usage': instance['AverageCpuUsage'],
                'average_network_usage': instance['AverageNetworkUsage']
            }
            template_data['instance'].append(instance_data)

        for instance in instances_scheduled_for_deletion:
            if instance['Creator'] is None:
                instance['Creator'] = 'Unknown'
            instance_data = {
                'instance_id': instance['InstanceID'],
                'instance_creator': instance['Creator'],
                'scheduled_for_deletion': True,
                'cost': instance['Cost'],
                'average_cpu_usage': instance['AverageCpuUsage'],
                'average_network_usage': instance['AverageNetworkUsage']
            }
            template_data['instance'].append(instance_data)

        return template_data

    def send_low_use_email(self, creator, low_use_instances, instances_scheduled_for_deletion, TemplateName=None):
        if creator is None:
            creator = ADMIN_EMAIL
        if TemplateName is None:
            template_name = self.low_use_template_name
        else:
            template_name = TemplateName

        source = SES_EMAIL
        destination = {
            'ToAddresses':[creator]
        }
        template_data = self.get_low_use_template_data(creator,
                                                       low_use_instances,
                                                       instances_scheduled_for_deletion)
        template_data_json = json.dumps(template_data)
        logger.info(template_data)
        response = self.ses.send_templated_email(
            Source=source,
            Destination=destination,
            Template=template_name,
            TemplateData=template_data_json
        )
        return response

    def send_admin_report(self, low_use_instances, instances_scheduled_for_deletion):
        return self.send_low_use_email(ADMIN_EMAIL, low_use_instances,
                                       instances_scheduled_for_deletion,
                                       TemplateName=self.admin_template_name)
