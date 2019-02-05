
import torch
import torchvision
import torchvision.transforms as transforms
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
import numpy as np
import torch.optim as optim
import os
import math
from torch.autograd import Variable
from utils import progress_bar
from tensorboardX import SummaryWriter 


writer = SummaryWriter('tensorboard_no_clamp/')


# hyper paramerters
# some are created as global variables and will be assigned with the right value later
batch_size = 100
lamda_cot_max = 10
lamda_diff_max = 0.5
lamda_cot = 0
lamda_diff = 0
best_acc1 = 0
best_acc2 = 0

class co_train_classifier(nn.Module):
    def __init__(self):
        super(co_train_classifier, self).__init__()
        self.c1 = nn.Conv2d(3, 128, kernel_size=3, padding=1)
        self.b1 = nn.BatchNorm2d(128)
        self.r1 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.c2 = nn.Conv2d(128, 128, kernel_size=3, padding=1)
        self.b2 = nn.BatchNorm2d(128)
        self.r2 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.c3 = nn.Conv2d(128, 128, kernel_size=3, padding=1)
        self.b3 = nn.BatchNorm2d(128)
        self.r3 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.m1 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.d1 = nn.Dropout2d(p=0.5)

        self.c4 = nn.Conv2d(128, 256, kernel_size=3, padding=1)
        self.b4 = nn.BatchNorm2d(256)
        self.r4 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.c5 = nn.Conv2d(256, 256, kernel_size=3, padding=1)
        self.b5 = nn.BatchNorm2d(256)
        self.r5 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.c6 = nn.Conv2d(256, 256, kernel_size=3, padding=1)
        self.b6 = nn.BatchNorm2d(256)
        self.r6 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.m2 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.d2 = nn.Dropout2d(p=0.5)

        self.c7 = nn.Conv2d(256, 512, kernel_size=3, padding=1)
        self.b7 = nn.BatchNorm2d(512)
        self.r7 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.c8 = nn.Conv2d(512, 256, kernel_size=3, padding=1)
        self.b8 = nn.BatchNorm2d(256)
        self.r8 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.c9 = nn.Conv2d(256, 128, kernel_size=3, padding=1)
        self.b9 = nn.BatchNorm2d(128)
        self.r9 = nn.LeakyReLU(negative_slope=0.1, inplace=True)

        self.fc = nn.Linear(128, 10)
        self.sf = nn.Softmax(dim = 1)

    def forward(self, x):
        x = self.c1(x)
        x = self.b1(x)
        x = self.r1(x)
        x = self.c2(x)
        x = self.b2(x)
        x = self.r2(x)
        x = self.c3(x)
        x = self.b3(x)
        x = self.r3(x)
        x = self.m1(x)
        x = self.d1(x)


        x = self.c4(x)
        x = self.b4(x)
        x = self.r4(x)
        x = self.c5(x)
        x = self.b5(x)
        x = self.r5(x)
        x = self.c6(x)
        x = self.b6(x)
        x = self.r6(x)
        x = self.m2(x)
        x = self.d2(x)

        x = self.c7(x)
        x = self.b7(x)
        x = self.r7(x)
        x = self.c8(x)
        x = self.b8(x)
        x = self.r8(x)
        x = self.c9(x)
        x = self.b9(x)
        x = self.r9(x)
        x = torch.mean(torch.mean(x, dim=3), dim=2)
        x_logit = self.fc(x)
        x_softmax = self.sf(x_logit)
        return x_softmax, x_logit


def adjust_learning_rate(optimizer, epoch):
    """cosine scheduling"""
    epoch = epoch + 1
    lr = 0.05*(1.0+math.cos((epoch-1)*math.pi/600))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def adjust_lamda(epoch):
    epoch = epoch + 1
    global lamda_cot
    global lamda_diff
    if epoch <= 80:
        lamda_cot = lamda_cot_max*math.exp(-5*(1-epoch/80)**2)
        lamda_diff = lamda_diff_max*math.exp(-5*(1-epoch/80)**2)
    else: 
        lamda_cot = lamda_cot_max
        lamda_diff = lamda_diff_max    




# The default averaging means that the loss is actually not the KL Divergence because the terms are already probability weighted. A future release of PyTorch may move the default loss closer to the mathematical definition.
# To get the real KL Divergence, use size_average=False, and then divide the output by the batch size.

# Example:
# >>> loss = nn.KLDivLoss(size_average=False)
# >>> batch_size = 5
# >>> log_probs1 = F.log_softmax(torch.randn(batch_size, 10), 1)
# >>> probs2 = F.softmax(torch.randn(batch_size, 10), 1)
# >>> loss(log_probs1, probs2) / batch_size
# version 0.4.1

def jsd(p,q):
    kld = nn.KLDivLoss(size_average=False)
    S = nn.Softmax(dim = 1)
    LS = nn.LogSoftmax(dim = 1)
    a = S(p)
    b = S(q)
    c = LS(0.5*(p + q))

    return (0.5*kld(c,a) + 0.5*kld(c, b))/92

def loss_sup(logit1, logit2, labels_S1, labels_S2):
    # CE, by default, is averaged over each loss element in the batch
    ce = nn.CrossEntropyLoss() 
    loss1 = ce(logit1, labels_S1)
    loss2 = ce(logit2, labels_S2) 
    return loss1+loss2

def loss_cot(logit1, logit2):
# the Jensen-Shannon divergence between p1(x) and p2(x)
    return jsd(logit1, logit2)

def loss_diff(logit1, logit2, perturbed_logit1, perturbed_logit2, U_logit1, U_logit2, perturbed_logit_U1, perturbed_logit_U2):
    S = nn.Softmax(dim = 1)
    LS = nn.LogSoftmax(dim = 1)
    
    a = S(logit2) * LS(perturbed_logit1)
    a = torch.sum(a)
    # a = a/8

    b = S(logit1) * LS(perturbed_logit2)
    b = torch.sum(b)
    # b = b/8

    c = S(U_logit2) * LS(perturbed_logit_U1)
    c = torch.sum(c)
    # c = c/92
    
    d = S(U_logit1) * LS(perturbed_logit_U2)
    d = torch.sum(d)
    # d = d/92
    return -(a+b+c+d)/100

# This function is copied from the official website of Pytorch. 
# Note that we clip to -1, 1 instead of 0, 1
# def fgsm_attack(image, epsilon, data_grad):
#     # Collect the element-wise sign of the data gradient
#     sign_data_grad = data_grad.sign()
#     # Create the perturbed image by adjusting each pixel of the input image
#     perturbed_image = image + epsilon*sign_data_grad
#     # Adding clipping to maintain [-1,1] range
#     perturbed_image = torch.clamp(perturbed_image, -1, 1)
#     # Return the perturbed image
#     return perturbed_image

# def get_adv_example(net, inputs, labels):
#     # generate adversarial example 
#     net.eval()
#     inputs.requires_grad = True
#     ce = nn.CrossEntropyLoss() 
#     _,  logits = net(inputs)
#     loss = ce(logits, labels)
#     net.zero_grad()
#     loss.backward(retain_graph=True)
#     inputs_grad = inputs.grad.data
#     perturbed_data = fgsm_attack(inputs, 0.1, inputs_grad)
#     net.train()
#     return perturbed_data


def get_adv_example(net, inputs, labels, optimizer):
    net.eval()
    inputs.requires_grad_()
    optimizer.zero_grad()
    ce = nn.CrossEntropyLoss()
    _, outputs = net(inputs)
    loss = ce(outputs,labels)
    loss.backward()
    epsilon = 0.02
    x_grad = torch.sign(inputs.grad)
    # x_adversarial = torch.clamp(inputs.detach()+epsilon*x_grad,-1,1)   
    # the author said that they didn't clamp 
    x_adversarial = inputs.detach()+epsilon*x_grad
    net.train()
    return x_adversarial

# labelled data propotion 4000/50000 for cifar 10 
# unlabelled data propotion 46000/50000 for cifar 10 
# standard data augmentation on cifar10
transform = transforms.Compose([
    # transforms.RandomCrop(32, padding=4),
    transforms.RandomAffine(0, translate=(1/16,1/16)),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])


transform_test = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])




testset = torchvision.datasets.CIFAR10(root='./data', train=False, download=True, transform=transform_test)
testloader = torch.utils.data.DataLoader(testset, batch_size=batch_size, shuffle=True, num_workers=2)

classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')


trainset = torchvision.datasets.CIFAR10(root='./data', train=True,
                                        download=True, transform=transform)

trainloader = torch.utils.data.DataLoader(trainset, batch_size=1,
                                          shuffle=False, num_workers=2)

S_loader1 = torch.utils.data.DataLoader(trainset, batch_size=8,
                                          shuffle=True, num_workers=2)

S_loader2 = torch.utils.data.DataLoader(trainset, batch_size=8,
                                          shuffle=True, num_workers=2)


S_idx = []
U_idx = []
dataiter = iter(trainloader)
train = [[],[],[],[],[],[],[],[],[],[]]
for i in range(50000):
    inputs, labels = dataiter.next()
    train[labels].append(i)

for i in range(10):
    S_idx = S_idx + train[i][0:400]
    U_idx = U_idx + train[i][400:]

S_sampler = torch.utils.data.SubsetRandomSampler(S_idx)
U_sampler = torch.utils.data.SubsetRandomSampler(U_idx)



S_loader1 = torch.utils.data.DataLoader(
        trainset, batch_size=8, sampler=S_sampler,
        num_workers=2, pin_memory=True)

S_loader2 = torch.utils.data.DataLoader(
        trainset, batch_size=8, sampler=S_sampler,
        num_workers=2, pin_memory=True)

U_loader = torch.utils.data.DataLoader(
        trainset, batch_size=92, sampler=U_sampler,
        num_workers=2, pin_memory=True)



step = len(trainset)/batch_size
# training
net1 = co_train_classifier()
net2 = co_train_classifier()

net1.cuda()
net2.cuda()
# net1.load_state_dict(torch.load('./checkpoint/co_train_classifier_1_599.pkl'))
# net2.load_state_dict(torch.load('./checkpoint/co_train_classifier_2_599.pkl'))
# print("scuccessfully load")
params = list(net1.parameters()) + list(net2.parameters())
# stochastic gradient descent with momentum 0.9 and weight decay0.0001 in paper page 7
optimizer = optim.SGD(params, lr=0.05, momentum=0.9, weight_decay=0.0001)
ce = nn.CrossEntropyLoss() 



def train(epoch):
    net1.train()
    net2.train()

    adjust_learning_rate(optimizer, epoch)
    adjust_lamda(epoch)
    
    total_S1 = 0
    total_S2 = 0
    total_U1 = 0
    total_U2 = 0
    train_correct_S1 = 0
    train_correct_S2 = 0
    train_correct_U1 = 0
    train_correct_U2 = 0
    running_loss = 0.0
    ls = 0.0
    lc = 0.0 
    ld = 0.0
    i = 0

    # create iterator for b1, b2, bu
    S_iter1 = iter(S_loader1)
    S_iter2 = iter(S_loader2)
    U_iter = iter(U_loader)
    print('epoch:',epoch)
    print('\n')
    while(i < step):
        inputs_S1, labels_S1 = S_iter1.next()
        inputs_S2, labels_S2 = S_iter2.next()
        inputs_U, labels_U = U_iter.next() # note that label U will not be used for training. 

        inputs_S1 = inputs_S1.cuda()
        labels_S1 = labels_S1.cuda()
        inputs_S2 = inputs_S2.cuda()
        labels_S2 = labels_S2.cuda()
        inputs_U = inputs_U.cuda()    


        # generate adversarial example 1
        perturbed_data1 = get_adv_example(net1, inputs_S1, labels_S1, optimizer)
        perturbed_data2 = get_adv_example(net2, inputs_S2, labels_S2, optimizer)

        _, perturbed_logit1 = net1(perturbed_data2)
        _, perturbed_logit2 = net2(perturbed_data1)
       
        _, S_logit1 = net1(inputs_S1)
        _, S_logit2 = net2(inputs_S2)
        _, U_logit1 = net1(inputs_U)
        _, U_logit2 = net2(inputs_U)

        predictions_S1 = torch.max(S_logit1, 1)
        predictions_S2 = torch.max(S_logit2, 1)
        predictions_U1 = torch.max(U_logit1, 1)
        predictions_U2 = torch.max(U_logit2, 1)
        
        
        perturbed_data_U1 = get_adv_example(net1, inputs_U, predictions_U1[1], optimizer)
        perturbed_data_U2 = get_adv_example(net2, inputs_U, predictions_U2[1], optimizer)


        _, perturbed_logit_U1 = net1(perturbed_data_U2)
        _, perturbed_logit_U2 = net2(perturbed_data_U1)

        # zero the parameter gradients
        optimizer.zero_grad()
        net1.zero_grad()
        net2.zero_grad()

        
        Loss_sup = loss_sup(S_logit1, S_logit2, labels_S1, labels_S2)
        Loss_cot = loss_cot(U_logit1, U_logit2)
        Loss_diff = loss_diff(S_logit1, S_logit2, perturbed_logit1, perturbed_logit2, U_logit1, U_logit2, perturbed_logit_U1, perturbed_logit_U2)
        
        total_loss = Loss_sup + lamda_cot*Loss_cot + lamda_diff*Loss_diff

        # total_loss = Loss_sup 
        total_loss.backward()
        optimizer.step()


        train_correct_S1 += np.sum(predictions_S1[1].cpu().numpy() == labels_S1.cpu().numpy())
        total_S1 += labels_S1.size(0)

        train_correct_U1 += np.sum(predictions_U1[1].cpu().numpy() == labels_U.cpu().numpy())
        total_U1 += labels_U.size(0)

        train_correct_S2 += np.sum(predictions_S2[1].cpu().numpy() == labels_S2.cpu().numpy())
        total_S2 += labels_S2.size(0)

        train_correct_U2 += np.sum(predictions_U2[1].cpu().numpy() == labels_U.cpu().numpy())
        total_U2 += labels_U.size(0)
        
        running_loss += total_loss.item()
        ls += Loss_sup.item()
        lc += Loss_cot.item()
        ld += Loss_diff.item()
        # print statistics
        
        writer.add_scalars('data/loss', {'loss_sup': Loss_sup.item(), 'loss_cot': lamda_cot*Loss_cot.item(), 'loss_diff': lamda_diff*Loss_diff.item()}, (epoch+1)*(i+1))
        # writer.add_scalars('data/loss', {'loss_sup': Loss_sup.item()}, (epoch+1)*(i+1))

        writer.add_scalars('data/training_accuracy', {'net1 acc': 100. * (train_correct_S1) / (total_S1), 'net2 acc': 100. * (train_correct_S2) / (total_S2)}, (epoch+1)*(i+1))
        if (i+1)%50 == 0:
            print('net1 acc: %.3f%% | net2 acc: %.3f%% | total loss: %.3f | loss_sup: %.3f | loss_cot: %.3f | loss_diff: %.3f  '
                # % (100. * (train_correct_S1) / (total_S1), 100. * (train_correct_S2) / (total_S2), running_loss/(i+1), ls/(i+1)))

                % (100. * (train_correct_S1+train_correct_U1) / (total_S1+total_U1), 100. * (train_correct_S2+train_correct_U2) / (total_S2+total_U2), running_loss/(i+1), ls/(i+1), lc/(i+1), ld/(i+1)))
            
        i = i + 1
    torch.save(net1.state_dict(), './checkpoint_no_clamp/co_train_classifier_1_'+str(epoch)+'.pkl')
    torch.save(net2.state_dict(), './checkpoint_no_clamp/co_train_classifier_2_'+str(epoch)+'.pkl')

def test(epoch):
    net1.eval()
    net2.eval()
    global best_acc1 
    global best_acc2
    correct1 = 0
    correct2 = 0
    total1 = 0
    total2 = 0
    with torch.no_grad():
        for batch_idx, (inputs, targets) in enumerate(testloader):
            inputs = inputs.cuda()
            targets = targets.cuda()

            _, outputs1 = net1(inputs)
            predicted1 = outputs1.max(1)
            total1 += targets.size(0)
            correct1 += predicted1[1].eq(targets).sum().item()

            _, outputs2 = net2(inputs)
            predicted2 = outputs2.max(1)
            total2 += targets.size(0)
            correct2 += predicted2[1].eq(targets).sum().item()
            
            progress_bar(batch_idx, len(testloader), '\nnet1 acc: %.3f%% (%d/%d) | net2 acc: %.3f%% (%d/%d)'
                % (100.*correct1/total1, correct1, total1, 100.*correct2/total2, correct2, total2))

    writer.add_scalars('data/testing_accuracy', {'net1 acc': 100.*correct1/total1, 'net2 acc': 100.*correct2/total2}, epoch)
    # Save checkpoint.
    acc1 = 100.*correct1/total1
    acc2 = 100.*correct2/total2
 

    # if acc1 > best_acc1 or acc2 > best_acc2:
    #     print('Saving..')
    #     if not os.path.isdir('checkpoint'):
    #         os.mkdir('checkpoint')
    #     torch.save(net1.state_dict(), './checkpoint/co_train_classifier_1.pkl')
    #     torch.save(net2.state_dict(), './checkpoint/co_train_classifier_2.pkl')
    #     best_acc1 = acc1
    #     best_acc2 = acc2

start_epoch = 0
for epoch in range(start_epoch, 600):
    train(epoch)
    test(epoch)

writer.export_scalars_to_json("./tensorboard_no_clamp/output.json")
writer.close()