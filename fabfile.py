# coding=utf-8

import os
import json
import uuid
import StringIO
from fabric.api import run, cd, env, prefix, sudo, put, roles, runs_once


env.roledefs = {
    'backend': ['35.165.201.184', '35.166.207.188', '35.165.121.101'],
    'frontend': ['35.166.94.244', '35.164.35.218']
}
env.hosts = env.roledefs['backend'] + env.roledefs['frontend']

env.user = 'ubuntu'
env.key_filename = 'ubuntu'

docker_repo = 'deb https://apt.dockerproject.org/repo ubuntu-trusty main'
hello_app_github_url = 'https://github.com/neoden/nv-hello-app'
app_port = 49160
app_inner_port = 8888
docker_app_name = 'ubuntu/hello-app'

backend_lan_ip = ['10.255.252.53', '10.255.252.21', '10.255.252.23']
frontend_lan_ip = ['10.255.252.34', '10.255.252.60']
lan_ip = backend_lan_ip + frontend_lan_ip


def trash_container(name):
    # drop existing container
    sudo('docker stop `sudo docker ps --no-trunc -aq -f name={}` || true'.format(name))
    sudo('docker rm `sudo docker ps --no-trunc -aq -f name={}` || true'.format(name))


def install_docker():
    # see manual at https://docs.docker.com/engine/installation/linux/ubuntulinux/
    sudo('apt-get -y install apt-transport-https ca-certificates')
    sudo('sudo apt-key adv --keyserver hkp://ha.pool.sks-keyservers.net:80 --recv-keys 58118E89F3A912897C070ADBF76221572C52609D')
    run('echo "{}" | sudo tee /etc/apt/sources.list.d/docker.list'.format(docker_repo))
    sudo('apt-get -y -qq update')
    # skip aufs enabling for now
    #sudo('apt-get install linux-image-extra-$(uname -r) linux-image-extra-virtual')
    sudo('apt-get -y install docker-engine')
    sudo('service docker restart')


@roles('backend')
def deploy_app():
    # deploy test node.js app from github
    repo_name = hello_app_github_url.split('/')[-1]
    run('rm -rf ' + repo_name)
    run('git clone ' + hello_app_github_url)
    with cd(repo_name):
        sudo('docker build -t {} .'.format(docker_app_name))

    # run app
    sudo('docker run --name hello --restart=always -p {}:{} -d {}'.format(app_port, app_inner_port, docker_app_name))


@roles('backend')
def back_init():
    # remove backend docker containers
    trash_container('hello')
    trash_container('consul')


@roles('backend')
def back_consul():
    # setup consul for backend
    sudo('rm -rf /etc/consul')
    sudo('mkdir /etc/consul')

    conf = json.load(open('backend.json'))
    conf['service']['id'] = uuid.uuid4().hex
    f = StringIO.StringIO()
    f.write(json.dumps(conf))

    put(f, '/etc/consul/backend.json', use_sudo=True)
    f.close()

    sudo('docker run --name consul --restart=always --net=host -d -v /etc/consul/:/consul/config consul agent -server -bootstrap-expect=3 -bind=`ifconfig eth0 | grep "inet addr:" | cut -d: -f2 | cut -d" " -f1`')


@roles('frontend')
def front_init():
    # remove frontend docker containers
    trash_container('nginx')
    trash_container('consul')
    trash_container('consul-template')


@roles('frontend')
def front_consul():
    # setup consul for frontend
    sudo('rm -rf /etc/consul')
    sudo('mkdir /etc/consul')

    sudo('docker run --name consul --restart=always --net=host -d -v /etc/consul/:/consul/config consul agent -bind=`ifconfig eth0 | grep "inet addr:" | cut -d: -f2 | cut -d" " -f1`')


@runs_once
@roles('backend')
def consul_join():
    # join consul cluster
    sudo('docker exec consul consul join ' + ' '.join(lan_ip))


@roles('frontend')
def front_setup():
    # setup and run frontend stuff
    sudo('rm -rf /etc/nginx')
    sudo('mkdir /etc/nginx')
    put('nginx.conf', '/etc/nginx/', use_sudo=True)
    put('nginx.ctmpl', '/etc/nginx/', use_sudo=True)

    # run nginx
    sudo('docker run --name nginx --restart=always --net=host -d -v /etc/nginx/nginx.conf:/etc/nginx/nginx.conf nginx')

    # run consul-template
    sudo('docker run -d --name consul-template --restart=always --net=host -v /etc/nginx/:/etc/ctmpl/ -v /var/run/docker.sock:/var/run/docker.sock -v `which docker`:/usr/bin/docker -v /usr/lib/x86_64-linux-gnu/:/usr/lib/x86_64-linux-gnu/:ro -v /lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu alterway/consul-template-nginx -consul=localhost:8500 -wait=2s -template="/etc/ctmpl/nginx.ctmpl:/etc/ctmpl/nginx.conf:docker restart nginx"')



# finally install everything with:
# fab back_init deploy_app back_consul front_init front_consul consul_join front_setup