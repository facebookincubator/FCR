# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#
FROM debian:latest

RUN \
        apt-get update &&\
        apt-get install -y openssh-server &&\
        mkdir /var/run/sshd

# SSH login fix. Otherwise user is kicked off after login
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

RUN echo "set show-all-if-ambiguous on" >> /etc/inputrc

# Create a test user and create a super secure password :)
RUN \
        adduser --disabled-password --gecos '' netbot \
        && echo 'netbot:bot1234' | chpasswd

EXPOSE 22

ADD startup.sh /usr/local/bin
RUN chmod +x /usr/local/bin/startup.sh
CMD /usr/local/bin/startup.sh
