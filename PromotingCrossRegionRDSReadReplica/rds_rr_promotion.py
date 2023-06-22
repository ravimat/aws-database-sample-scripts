import json
import time
import boto3
import os
import datetime
from datetime import datetime, timedelta

def promote_rr(rds_id,sregion):

    rds_client = boto3.client("rds",region_name=sregion)
    promo_status=0
    try:

        promote_response = rds_client.promote_read_replica(DBInstanceIdentifier=rds_id)
        print(f'Promotion started...waiting for instance available state.')
        time.sleep(5)
        get_rds_info = rds_client.describe_db_instances(DBInstanceIdentifier=rds_id)

        rds_status = get_rds_info['DBInstances'][0]['DBInstanceStatus']

        while rds_status != "available":
            time.sleep(30)
            get_rds_info = rds_client.describe_db_instances(DBInstanceIdentifier=rds_id)
            rds_status = get_rds_info['DBInstances'][0]['DBInstanceStatus']

        if rds_status == 'available':
            print (f'RDS instance {rds_id} successfully promoted as writer Instance!')
            promo_status=1


    except Exception as e:
        print('Exception = ',e)

    return promo_status

def get_cloudwatch_replica_lag(rds_id,sregion):
    session = boto3.session.Session(region_name=sregion)
   # cloudwatch = boto3.client('cloudwatch')
    cloudwatch = session.client('cloudwatch')
    result = cloudwatch.get_metric_data(
       MetricDataQueries=[
          {
              'Id': 'ec2data',
              'MetricStat': {
                  'Metric': {
                      'Namespace': 'AWS/RDS',
                      'MetricName': 'ReplicaLag',
                      'Dimensions': [
                          {
                              'Name': 'DBInstanceIdentifier',
                              'Value': rds_id
                          },
                      ]
                  },
                  'Period': 60,
                  'Stat': 'Maximum',
                  'Unit': 'Seconds'
              },
              'ReturnData': True
          },
        ],

        StartTime=datetime.utcnow() - timedelta(days=1/1440),
        EndTime=datetime.utcnow()
    )

    return result['MetricDataResults'][0]['Values']


def lambda_handler(event, context):

    # Populate the existing environment information

    vPDBIdentifier = os.environ['PRIMARY_DB_IDENTIFIER']
    vSDBIdentifier = os.environ['REPLICA_DB_IDENTIFIER']
    vRRLag = os.environ['ACCEPTABLE_RR_LAG_SECONDS']
    vPregion = os.environ['PRIMARY_REGION']
    vSregion = os.environ['SECONDARY_REGION']

    # Initialize session variables

    client = boto3.client("rds",region_name=vSregion)
    dnsclient = boto3.client("route53")

    try:

        get_rds = client.describe_db_instances(DBInstanceIdentifier=vSDBIdentifier)
        rds_status = get_rds['DBInstances'][0]['DBInstanceStatus']

        # Verifying if this is a read replica instance, if not, it would raise a key error exception and exit.
        check_db_mode = get_rds['DBInstances'][0]['ReadReplicaSourceDBInstanceIdentifier']

        print(f' This instance  is a reader node, proceeding further.')

        if (rds_status != 'available'):
            print(f'RDS replica {vSDBIdentifier} is not in AVAILABLE state, manual intervantion will require!')
        else:
            print (f'RDS replica {vSDBIdentifier} is in {rds_status} state, checking replica lag now..')
            lag_response = get_cloudwatch_replica_lag(vSDBIdentifier,vSregion)

            #print (response)
            if (lag_response[0] >= 0):
                if ( lag_response[0] > float(vRRLag) ):
                    print(f'Replica Lag[{lag_response}] is greater than acceptable range [{vRRLag}]. Please investigate replica lag manually and perform manual read replica promotion. Exiting Now!!')
                else:
                    print (f'Replica lag is {lag_response[0]} under acceptable range  {vRRLag} .')
                    print (f'Initiating promotion of read replica node {vSDBIdentifier} as new primary! ')
                    promote_results = promote_rr(vSDBIdentifier,vSregion)

                    if promote_results == 1:
                        print (f'{vSDBIdentifier} has been successfully promoted as new primary!')
                    else:
                        print(f'Promotion of reader node {vSDBIdentifier} not completed or initiated, please verify the replica status manually and complete next steps to complete the failover manually.')
            else:
                print('Error reading Replica Lag, verify if reader is in sync with primary server.')
    except KeyError as k:
        print(' This is NOT a reader node! Please connect to a RDS Reader instance!' , k)
    except Exception as e:
        print('Exception = ',e)
