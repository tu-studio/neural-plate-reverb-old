import torch
import torch.nn as nn
import torch.optim as optim
from torch.nn.utils import clip_grad_norm_
from utilities.ravepqmf import PQMF,  center_pad_next_pow_2



def train(encoder, decoder, train_loader, val_loader, criterion, optimizer, tensorboard_writer, num_epochs=25, device='cpu', n_bands=64, use_kl=False, sample_rate=44100):
    encoder.to(device)
    decoder.to(device)

    # Initialize PQMF
    pqmf = PQMF(100, n_bands).to(device)

    for epoch in range(num_epochs):
        #Training Loop
        encoder.train()
        decoder.train()


        #initialize epoch losses
        train_epoch_loss = 0
        train_epoch_kl_div = 0
        train_epoch_criterion = 0

        for batch, (dry_audio, wet_audio) in enumerate(train_loader):
            #reshape audio
            print(batch)
            dry_audio = dry_audio[0:1, :]
            wet_audio = wet_audio[0:1, :]  
           
            dry_audio = dry_audio.view(1, 1, -1)
            wet_audio = wet_audio.view(1, 1, -1)
            wet_audio = wet_audio[:,:, :dry_audio.shape[-1]]
            

            dry_audio, wet_audio = dry_audio.to(device), wet_audio.to(device)

            # Pad both dry and wet audio to next power of 2
            dry_audio = center_pad_next_pow_2(dry_audio)
            wet_audio = center_pad_next_pow_2(wet_audio)
            
            # Apply PQMF to input
            dry_audio_decomposed = pqmf(dry_audio)
            wet_audio_decomposed = pqmf(wet_audio)

            audio_difference_decomposed = wet_audio_decomposed - dry_audio_decomposed
            audio_difference = wet_audio - dry_audio
 
            # Zero the parameter gradients
            optimizer.zero_grad()

            # Forward pass through encoder
            encoder_outputs = []
            x = dry_audio_decomposed
            for block in encoder.blocks:
                x = block(x)
                encoder_outputs.append(x)
    
            # Get the final encoder output
            z= encoder_outputs.pop()

            # Reverse the list of encoder outputs for the decoder
            encoder_outputs = encoder_outputs[::-1]
            encoder_outputs.append(dry_audio_decomposed)

            # Forward pass through encoder
            if use_kl:
                mu, logvar = encoder(dry_audio_decomposed)
                z = encoder.reparameterize(mu, logvar)
                kl_div = (-0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp()))/ mu.shape[-1]
                train_epoch_kl_div += kl_div

            # Forward pass through decoder
            net_outputs_decomposed = decoder(z, encoder_outputs)

            net_outputs = pqmf.inverse(net_outputs_decomposed)

            # # Trim outputs to original length
            original_length = dry_audio.shape[-1]
            net_outputs = net_outputs[..., :original_length]
            wet_audio = wet_audio[..., :original_length]
            dry_audio = dry_audio[..., :original_length]

            # Compute loss
            loss = criterion(net_outputs + dry_audio, wet_audio)
            if use_kl:
                loss += kl_div
          
            # Output
            output = net_outputs + dry_audio

            # Add KL divergence to the loss
            train_epoch_loss += loss 
            
            train_epoch_criterion += loss
            

            # Backward pass and optimization
            loss.backward()

            # Gradient Clipping
            torch.nn.utils.clip_grad_norm_(encoder.parameters(), max_norm=1.0)
            torch.nn.utils.clip_grad_norm_(decoder.parameters(), max_norm=1.0)

            optimizer.step()

        
        train_avg_epoch_loss = train_epoch_loss / len(train_loader)
        train_avg_epoch_loss_criterion = train_epoch_criterion / len(train_loader)  
        if use_kl:
            train_avg_epoch_kl_div = train_epoch_kl_div / len(train_loader)

        # Log loss
        tensorboard_writer.add_scalar("Loss/ training loss", train_avg_epoch_loss, epoch)
        tensorboard_writer.add_scalar("Loss/ training criterion", train_avg_epoch_loss_criterion, epoch)
        if use_kl:
            tensorboard_writer.add_scalar("Loss/training kl_div", train_avg_epoch_kl_div, epoch)
        # Log audio samples
        tensorboard_writer.add_audio("Audio/TCN_Input", dry_audio.cpu().squeeze(0), epoch, sample_rate=sample_rate)
        tensorboard_writer.add_audio("Audio/TCN_Target", wet_audio.cpu().squeeze(0), epoch, sample_rate=sample_rate)
        tensorboard_writer.add_audio("Audio/TCN_output", output.cpu().squeeze(0), epoch, sample_rate=sample_rate)

        print(f'Epoch {epoch+1}/{num_epochs}, Training Loss: {train_avg_epoch_loss}')

        # Validation loop
        encoder.eval()
        decoder.eval()
        val_epoch_loss = 0
        val_epoch_kl_div = 0
        val_epoch_criterion = 0
        with torch.no_grad():
            for batch, (dry_audio, wet_audio) in enumerate(val_loader):
                #reshape audio
                dry_audio = dry_audio[0:1, :]
                wet_audio = wet_audio[0:1, :]  
            
                dry_audio = dry_audio.view(1, 1, -1)
                wet_audio = wet_audio.view(1, 1, -1)
                wet_audio = wet_audio[:,:, :dry_audio.shape[-1]]
                

                dry_audio, wet_audio = dry_audio.to(device), wet_audio.to(device)

                # Pad both dry and wet audio to next power of 2
                dry_audio = center_pad_next_pow_2(dry_audio)
                wet_audio = center_pad_next_pow_2(wet_audio)
                
                # Apply PQMF to input
                dry_audio_decomposed = pqmf(dry_audio)
                wet_audio_decomposed = pqmf(wet_audio)

                audio_difference_decomposed = wet_audio_decomposed - dry_audio_decomposed
                audio_difference = wet_audio - dry_audio
    
                # Zero the parameter gradients
                optimizer.zero_grad()

                # Forward pass through encoder
                encoder_outputs = []
                x = dry_audio_decomposed
                for block in encoder.blocks:
                    x = block(x)
                    encoder_outputs.append(x)
        
                # Get the final encoder output
                z= encoder_outputs.pop()

                # Reverse the list of encoder outputs for the decoder
                encoder_outputs = encoder_outputs[::-1]
                encoder_outputs.append(dry_audio_decomposed)

                # Forward pass through encoder
                if use_kl:
                    mu, logvar = encoder(dry_audio_decomposed)
                    z = encoder.reparameterize(mu, logvar)
                    kl_div = (-0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp()))/ mu.shape[-1]
                    val_epoch_kl_div += kl_div

                # Forward pass through decoder
                net_outputs_decomposed = decoder(z, encoder_outputs)

                net_outputs = pqmf.inverse(net_outputs_decomposed)

                # # Trim outputs to original length
                original_length = dry_audio.shape[-1]
                net_outputs = net_outputs[..., :original_length]
                wet_audio = wet_audio[..., :original_length]
                dry_audio = dry_audio[..., :original_length]

                # Compute loss
                loss = criterion(net_outputs + dry_audio, wet_audio)
                if use_kl:
                    loss += kl_div
            
                # Output
                output = net_outputs + dry_audio

                # Add KL divergence to the loss
                val_epoch_loss += loss 
                
                val_epoch_criterion += loss

        val_avg_epoch_loss = val_epoch_loss / len(val_loader)
        val_avg_epoch_loss_criterion = val_epoch_criterion / len(val_loader)  
        if use_kl:
            val_avg_epoch_kl_div = val_epoch_kl_div / len(val_loader)

        # Log loss
        tensorboard_writer.add_scalar("Loss/ validation loss", val_avg_epoch_loss, epoch)
        tensorboard_writer.add_scalar("Loss/ validation criterion", val_avg_epoch_loss_criterion, epoch)
        if use_kl:
            tensorboard_writer.add_scalar("Loss/validation kl_div", val_avg_epoch_kl_div, epoch)


    tensorboard_writer.flush()

    print('Finished Training')

